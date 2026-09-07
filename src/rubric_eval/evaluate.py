"""Assemble a per-item result from a rubric.

``evaluate_item_deterministic`` — deterministic layer only (no judge). Judged
dimensions are resolved only as far as "can this be evaluated at all?".

``evaluate_item`` — the full pipeline: deterministic layer, then the judge layer
(instruction-following resolution + N-run judged-dimension scoring + evidence
verification + consistency aggregation), then the verdict and its stability.

Failure containment: a provider error or a malformed judge response never
propagates out of ``evaluate_item``. Individual runs / dimensions / the gate are
recorded as errored, and the item still produces a result.
"""

from __future__ import annotations

from .checks.deterministic import run_deterministic_dimension
from .checks.evidence import resolve_evidence_requirement, verify_evidence
from .checks.instruction import evaluate_gate, gate_status
from .consistency import aggregate_scores, reliability_label, summarize_evidence
from .dataset import EvalItem
from .errors import ProviderError
from .judge import (
    build_dimension_prompt,
    build_instruction_prompt,
    call_judge,
    parse_dimension_judgment,
    parse_instruction_judgments,
)
from .models import JUDGED_TYPES, Dimension, DimensionType, Rubric
from .providers.base import Provider
from .results import (
    DimensionResult,
    DimensionStatus,
    GateResult,
    InstructionStatus,
    ItemResult,
    JudgeRunResult,
    ReliabilityLabel,
)
from .scoring import compute_verdict, indicative_score
from .stability import stability_for_item

_JUDGE_MAX_TOKENS = 1024


# --------------------------------------------------------------------------- #
# Deterministic-only path (Checkpoint 2)
# --------------------------------------------------------------------------- #


def evaluate_item_deterministic(rubric: Rubric, item: EvalItem) -> ItemResult:
    dimensions: list[DimensionResult] = []
    for dim in rubric.dimensions:
        if dim.type is DimensionType.GATE:
            dimensions.append(
                DimensionResult(
                    dimension_id=dim.id,
                    type=dim.type,
                    status=DimensionStatus.EVALUATED,
                    gate=evaluate_gate(dim, item),
                )
            )
        elif dim.type is DimensionType.DETERMINISTIC:
            dimensions.append(run_deterministic_dimension(dim, item.candidate_response))
        elif dim.type in JUDGED_TYPES:
            availability = resolve_evidence_requirement(dim, item)
            dimensions.append(
                DimensionResult(
                    dimension_id=dim.id,
                    type=dim.type,
                    status=(
                        DimensionStatus.PENDING_JUDGE
                        if availability.can_evaluate
                        else DimensionStatus.NOT_EVALUATED
                    ),
                    not_evaluated_reason=(
                        None if availability.can_evaluate else availability.reason
                    ),
                )
            )

    verdict = compute_verdict(rubric, dimensions)
    return ItemResult(
        item_id=item.id,
        task=item.task,
        candidate_response=item.candidate_response,
        scenario=item.scenario,
        author_note=item.author_note,
        dimensions=dimensions,
        verdict=verdict,
        indicative_score=indicative_score(dimensions),
    )


# --------------------------------------------------------------------------- #
# Full pipeline (Checkpoint 3)
# --------------------------------------------------------------------------- #


def evaluate_item(
    rubric: Rubric,
    item: EvalItem,
    provider: Provider,
    *,
    runs: int | None = None,
    judge_temperature: float = 0.0,
) -> ItemResult:
    n_runs = runs if runs is not None else rubric.reliability.runs_default
    errors: list[str] = []
    dimensions: list[DimensionResult] = []
    runs_by_dim: dict[str, list[JudgeRunResult]] = {}

    for dim in rubric.dimensions:
        if dim.type is DimensionType.GATE:
            dimensions.append(
                _evaluate_gate_dimension(rubric, dim, item, provider, judge_temperature, errors)
            )
        elif dim.type is DimensionType.DETERMINISTIC:
            dimensions.append(run_deterministic_dimension(dim, item.candidate_response))
        elif dim.type in JUDGED_TYPES:
            result = _evaluate_judged_dimension(
                rubric, dim, item, provider, n_runs, judge_temperature, errors
            )
            dimensions.append(result)
            if result.runs and result.status is DimensionStatus.EVALUATED:
                runs_by_dim[dim.id] = result.runs

    verdict = compute_verdict(rubric, dimensions)
    item_result = ItemResult(
        item_id=item.id,
        task=item.task,
        candidate_response=item.candidate_response,
        scenario=item.scenario,
        author_note=item.author_note,
        dimensions=dimensions,
        verdict=verdict,
        indicative_score=indicative_score(dimensions),
        errors=errors,
    )
    item_result.verdict_stability = stability_for_item(rubric, item_result, runs_by_dim, n_runs)
    return item_result


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #


def _evaluate_gate_dimension(
    rubric: Rubric,
    dim: Dimension,
    item: EvalItem,
    provider: Provider,
    temperature: float,
    errors: list[str],
) -> DimensionResult:
    gate: GateResult = evaluate_gate(dim, item)

    pending_idx = [
        i
        for i, inst in enumerate(gate.instructions)
        if inst.status is InstructionStatus.PENDING_JUDGE
    ]
    if pending_idx:
        texts = [gate.instructions[i].text for i in pending_idx]
        system, user = build_instruction_prompt(item, texts)
        try:
            call = call_judge(
                provider,
                system=system,
                user=user,
                parse=lambda t: parse_instruction_judgments(t, len(texts)),
                temperature=temperature,
                metadata={"eval_key": f"{item.id}::__gate__"},
                max_tokens=_JUDGE_MAX_TOKENS,
            )
        except ProviderError as exc:
            errors.append(f"instruction gate: provider error: {exc}")
            _mark_instructions_error(gate, pending_idx, f"provider error: {exc}")
        else:
            if call.parsed is None:
                errors.append(f"instruction gate: {call.error}")
                _mark_instructions_error(gate, pending_idx, call.error or "judge error")
            else:
                for local_i, gate_i in enumerate(pending_idx):
                    judgment = call.parsed[local_i]
                    inst = gate.instructions[gate_i]
                    inst.status = (
                        InstructionStatus.PASS if judgment.passed else InstructionStatus.FAIL
                    )
                    inst.detail = judgment.rationale
                    if judgment.evidence_quote:
                        inst.evidence = verify_evidence(
                            judgment.evidence_quote, item.candidate_response
                        )

    gate.status = gate_status(gate.instructions)
    return DimensionResult(
        dimension_id=dim.id,
        type=dim.type,
        status=DimensionStatus.EVALUATED,
        gate=gate,
    )


def _mark_instructions_error(gate: GateResult, indices: list[int], detail: str) -> None:
    for i in indices:
        gate.instructions[i].status = InstructionStatus.ERROR
        gate.instructions[i].detail = detail


# --------------------------------------------------------------------------- #
# Judged dimensions
# --------------------------------------------------------------------------- #


def _evaluate_judged_dimension(
    rubric: Rubric,
    dim: Dimension,
    item: EvalItem,
    provider: Provider,
    n_runs: int,
    temperature: float,
    errors: list[str],
) -> DimensionResult:
    availability = resolve_evidence_requirement(dim, item)
    if not availability.can_evaluate:
        return DimensionResult(
            dimension_id=dim.id,
            type=dim.type,
            status=DimensionStatus.NOT_EVALUATED,
            not_evaluated_reason=availability.reason,
        )

    system, user = build_dimension_prompt(rubric, dim, item)
    run_results: list[JudgeRunResult] = [
        _judge_one_run(provider, system, user, rubric, dim, item, run_index, temperature)
        for run_index in range(n_runs)
    ]

    stats = aggregate_scores(
        run_results, disagreement_threshold=rubric.reliability.disagreement_threshold
    )
    evidence_summary = summarize_evidence(run_results)

    if stats.n_valid == 0:
        errors.append(f"dimension '{dim.id}': all {n_runs} judge run(s) failed — not scored")
        return DimensionResult(
            dimension_id=dim.id,
            type=dim.type,
            status=DimensionStatus.NOT_EVALUATED,
            not_evaluated_reason=f"all {n_runs} judge run(s) failed",
            runs=run_results,
            judge_error_count=stats.judge_error_count,
            reliability_label=ReliabilityLabel.NOT_APPLICABLE,
            evidence_all_verified=evidence_summary["evidence_all_verified"],
            evidence_any_unverified=evidence_summary["evidence_any_unverified"],
        )

    if stats.judge_error_count:
        errors.append(
            f"dimension '{dim.id}': {stats.judge_error_count} of {n_runs} judge "
            f"run(s) failed (scored from the {stats.n_valid} that succeeded)"
        )

    return DimensionResult(
        dimension_id=dim.id,
        type=dim.type,
        status=DimensionStatus.EVALUATED,
        runs=run_results,
        scores=stats.scores,
        mean=round(stats.mean, 4) if stats.mean is not None else None,
        stdev=round(stats.stdev, 4) if stats.stdev is not None else None,
        minimum=stats.minimum,
        maximum=stats.maximum,
        pairwise_disagreement_rate=(
            round(stats.pairwise_disagreement_rate, 4)
            if stats.pairwise_disagreement_rate is not None
            else None
        ),
        reliability_label=reliability_label(stats, rubric.reliability),
        judge_error_count=stats.judge_error_count,
        evidence_all_verified=evidence_summary["evidence_all_verified"],
        evidence_any_unverified=evidence_summary["evidence_any_unverified"],
    )


def _judge_one_run(
    provider: Provider,
    system: str,
    user: str,
    rubric: Rubric,
    dim: Dimension,
    item: EvalItem,
    run_index: int,
    temperature: float,
) -> JudgeRunResult:
    metadata = {"eval_key": f"{item.id}::{dim.id}", "run_index": run_index}
    try:
        call = call_judge(
            provider,
            system=system,
            user=user,
            parse=lambda t: parse_dimension_judgment(t, rubric.scale),
            temperature=temperature,
            metadata=metadata,
            max_tokens=_JUDGE_MAX_TOKENS,
        )
    except ProviderError as exc:
        return JudgeRunResult(run_index=run_index, error=f"provider error: {exc}")

    if call.parsed is None:
        return JudgeRunResult(
            run_index=run_index,
            attempts=call.attempts,
            raw_response=call.raw,
            error=call.error,
        )

    judgment = call.parsed
    evidence = None
    if dim.type is DimensionType.REFERENCE_GROUNDED:
        evidence = verify_evidence(judgment.evidence_quote, item.reference)
    elif (
        dim.type is DimensionType.SPEC_GROUNDED and item.has_reference() and judgment.evidence_quote
    ):
        evidence = verify_evidence(judgment.evidence_quote, item.reference)

    return JudgeRunResult(
        run_index=run_index,
        score=judgment.score,
        rationale=judgment.rationale,
        evidence=evidence,
        attempts=call.attempts,
        raw_response=call.raw,
    )


# --------------------------------------------------------------------------- #
# Batch helper
# --------------------------------------------------------------------------- #


def safe_evaluate_item(
    rubric: Rubric,
    item: EvalItem,
    provider: Provider,
    *,
    runs: int | None = None,
    judge_temperature: float = 0.0,
) -> ItemResult:
    """Wrap ``evaluate_item`` so an unexpected error on one item never aborts a
    batch. ``evaluate_item`` already contains provider/parse failures internally;
    this is defence in depth."""
    try:
        return evaluate_item(rubric, item, provider, runs=runs, judge_temperature=judge_temperature)
    except Exception as exc:  # noqa: BLE001 - deliberately keep the batch alive
        from .results import GateStatus, Verdict, VerdictExplanation

        return ItemResult(
            item_id=item.id,
            task=item.task,
            candidate_response=item.candidate_response,
            scenario=item.scenario,
            author_note=item.author_note,
            dimensions=[],
            verdict=VerdictExplanation(
                verdict=Verdict.UNRESOLVED,
                gate_status=GateStatus.ERROR,
                deterministic_all_passed=False,
                notes=[f"item evaluation failed: {type(exc).__name__}: {exc}"],
            ),
            errors=[f"{type(exc).__name__}: {exc}"],
        )
