"""Verdict engine.

Turns a set of dimension results into one of:

    Fail  <  Needs work  <  Acceptable  <  Excellent        (resolved)
    Unresolved                                               (judge layer not run)

Rules, in order:

1. Instruction-following gate FAILED            -> Fail
2. A configured safety dimension FAILED         -> Fail or cap at "Needs work"
   (per rubric.verdict.safety_failure_verdict)
3. Anything still unresolved (a judged dimension awaiting the judge, or the
   gate PENDING)                                -> Unresolved
4. Otherwise, compute from the evaluated judged dimensions:
     * cap at "Needs work" if any deterministic check failed
     * cap at "Needs work" if any judged dimension mean is below the
       needs-work floor
     * base = Excellent / Acceptable / Needs work from the mean of judged means
     * verdict = min(base, cap)

A dimension that is NOT_EVALUATED (required evidence absent) is never treated
as a zero: it is excluded from the mean and noted.
"""

from __future__ import annotations

from .models import DimensionType, Rubric
from .results import (
    VERDICT_ORDER,
    DimensionResult,
    DimensionStatus,
    GateStatus,
    Verdict,
    VerdictExplanation,
)

_JUDGED_TYPES = {
    DimensionType.REFERENCE_GROUNDED,
    DimensionType.SPEC_GROUNDED,
    DimensionType.JUDGED,
}


def _min_verdict(a: Verdict, b: Verdict) -> Verdict:
    return a if VERDICT_ORDER[a] <= VERDICT_ORDER[b] else b


def compute_verdict(rubric: Rubric, dimensions: list[DimensionResult]) -> VerdictExplanation:
    gate = next((d.gate for d in dimensions if d.gate is not None), None)
    gate_status = gate.status if gate is not None else GateStatus.PASS

    det = [d for d in dimensions if d.type is DimensionType.DETERMINISTIC]
    det_all_passed = all(bool(d.deterministic_passed) for d in det) if det else True

    judged = [d for d in dimensions if d.type in _JUDGED_TYPES]
    evaluated = [d for d in judged if d.status is DimensionStatus.EVALUATED and d.mean is not None]
    not_evaluated = [d.dimension_id for d in judged if d.status is DimensionStatus.NOT_EVALUATED]
    pending = [d.dimension_id for d in judged if d.status is DimensionStatus.PENDING_JUDGE]

    capped_by: list[str] = []
    notes: list[str] = []

    # 1. gate failure
    if gate_status is GateStatus.FAIL:
        return VerdictExplanation(
            verdict=Verdict.FAIL,
            gate_status=gate_status,
            deterministic_all_passed=det_all_passed,
            not_evaluated_dimensions=not_evaluated,
            capped_by=["instruction-following gate failed"],
        )

    # 2. safety dimension failure
    safety_failed = [
        d.dimension_id
        for d in det
        if d.dimension_id in rubric.verdict.safety_dimension_ids and not d.deterministic_passed
    ]
    if safety_failed and rubric.verdict.safety_failure_verdict == "fail":
        return VerdictExplanation(
            verdict=Verdict.FAIL,
            gate_status=gate_status,
            deterministic_all_passed=det_all_passed,
            not_evaluated_dimensions=not_evaluated,
            capped_by=[f"safety dimension(s) failed: {', '.join(safety_failed)}"],
        )

    # 3. unresolved
    unresolved = list(pending)
    gate_note = None
    if gate_status is GateStatus.PENDING:
        unresolved.append("<instruction-following gate>")
        gate_note = "The instruction-following gate has not been evaluated by the judge layer."
    elif gate_status is GateStatus.ERROR:
        unresolved.append("<instruction-following gate>")
        gate_note = "The instruction-following gate could not be evaluated (judge/provider error)."
    if unresolved:
        notes = []
        if gate_note:
            notes.append(gate_note)
        if pending:
            notes.append(
                f"Judged dimensions not yet evaluated by the judge layer: {', '.join(pending)}."
            )
        notes.append("The verdict is provisional.")
        return VerdictExplanation(
            verdict=Verdict.UNRESOLVED,
            gate_status=gate_status,
            deterministic_all_passed=det_all_passed,
            evaluated_judged_dimensions=[d.dimension_id for d in evaluated],
            not_evaluated_dimensions=not_evaluated,
            unresolved_dimensions=unresolved,
            notes=notes,
        )

    # 4. resolved — compute
    cap = Verdict.EXCELLENT
    if not det_all_passed:
        cap = _min_verdict(cap, Verdict.NEEDS_WORK)
        capped_by.append("one or more deterministic checks failed")
    if safety_failed:  # reaches here only when safety_failure_verdict == "needs_work"
        cap = _min_verdict(cap, Verdict.NEEDS_WORK)
        capped_by.append(f"safety dimension(s) failed: {', '.join(safety_failed)}")

    judged_mean: float | None = None
    if not evaluated:
        base = Verdict.ACCEPTABLE
        if not_evaluated:
            notes.append(
                "judged dimensions not evaluated: "
                f"{', '.join(not_evaluated)} — these were NOT scored as zero"
            )
    else:
        means = [float(d.mean) for d in evaluated]  # type: ignore[arg-type]
        judged_mean = sum(means) / len(means)
        below_floor = [
            d.dimension_id
            for d in evaluated
            if float(d.mean) < rubric.verdict.needs_work_floor_any  # type: ignore[arg-type]
        ]
        if below_floor:
            cap = _min_verdict(cap, Verdict.NEEDS_WORK)
            capped_by.append(
                f"dimension(s) below the needs-work floor "
                f"({rubric.verdict.needs_work_floor_any}): {', '.join(below_floor)}"
            )
        if judged_mean >= rubric.verdict.excellent_min_mean:
            base = Verdict.EXCELLENT
        elif judged_mean >= rubric.verdict.acceptable_min_mean:
            base = Verdict.ACCEPTABLE
        else:
            base = Verdict.NEEDS_WORK
        if not_evaluated:
            notes.append(
                "judged dimensions not evaluated: "
                f"{', '.join(not_evaluated)} — excluded from the mean, NOT scored as zero"
            )

    final = _min_verdict(base, cap)
    return VerdictExplanation(
        verdict=final,
        gate_status=gate_status,
        deterministic_all_passed=det_all_passed,
        judged_mean=judged_mean,
        evaluated_judged_dimensions=[d.dimension_id for d in evaluated],
        not_evaluated_dimensions=not_evaluated,
        capped_by=capped_by,
        notes=notes,
    )


def indicative_score(dimensions: list[DimensionResult]) -> float | None:
    """Unweighted mean of the evaluated judged-dimension means, rounded to 2 dp.

    Labelled 'indicative' everywhere it appears: it is a convenience summary,
    not the verdict and not a calibrated metric.
    """
    means = [
        float(d.mean)
        for d in dimensions
        if d.type in _JUDGED_TYPES and d.status is DimensionStatus.EVALUATED and d.mean is not None
    ]
    if not means:
        return None
    return round(sum(means) / len(means), 2)
