"""Verdict stability across the N judged runs.

Instruction judging runs once (not per judged run), so the gate is fixed across
runs. Per-run verdict variation comes only from the judged-dimension scores:
for run *i*, each evaluable judged dimension is scored with that single run's
score, and ``compute_verdict`` is re-run.

Rules:
  * A run in which any evaluable judged dimension hit a judge error is recorded
    as 'Unresolved' for that run (we cannot compute a clean verdict for it).
  * The modal verdict is the most frequent one; ties resolve to the more
    conservative (lower-ranked) verdict, with 'Unresolved' ranked below 'Fail'.
"""

from __future__ import annotations

from collections import Counter

from .models import Rubric
from .results import (
    VERDICT_ORDER,
    DimensionResult,
    DimensionStatus,
    ItemResult,
    JudgeRunResult,
    Verdict,
    VerdictStabilityResult,
)
from .scoring import compute_verdict

# Conservative ordering for tie-breaking (Unresolved is the safest call).
_STABILITY_ORDER: dict[Verdict, int] = {Verdict.UNRESOLVED: -1, **VERDICT_ORDER}


def _modal_conservative(verdicts: list[Verdict]) -> Verdict:
    counts = Counter(verdicts)
    top = max(counts.values())
    tied = [v for v, c in counts.items() if c == top]
    return min(tied, key=lambda v: _STABILITY_ORDER[v])


def compute_verdict_stability(
    rubric: Rubric,
    final_dimensions: list[DimensionResult],
    runs_by_dim: dict[str, list[JudgeRunResult]],
    n_runs: int,
) -> VerdictStabilityResult:
    per_run: list[Verdict] = []

    for run_idx in range(n_runs):
        run_dims: list[DimensionResult] = []
        run_has_error = False

        for dim in final_dimensions:
            runs = runs_by_dim.get(dim.dimension_id)
            if runs is None:
                # gate / deterministic / not-evaluated judged: unchanged across runs
                run_dims.append(dim)
                continue
            jr = runs[run_idx] if run_idx < len(runs) else None
            if jr is not None and jr.score is not None:
                run_dims.append(
                    DimensionResult(
                        dimension_id=dim.dimension_id,
                        type=dim.type,
                        status=DimensionStatus.EVALUATED,
                        mean=float(jr.score),
                        scores=[jr.score],
                    )
                )
            else:
                run_has_error = True
                run_dims.append(
                    DimensionResult(
                        dimension_id=dim.dimension_id,
                        type=dim.type,
                        status=DimensionStatus.NOT_EVALUATED,
                        not_evaluated_reason="judge error on this run",
                    )
                )

        if run_has_error:
            per_run.append(Verdict.UNRESOLVED)
        else:
            per_run.append(compute_verdict(rubric, run_dims).verdict)

    distribution = {v.value: c for v, c in Counter(per_run).items()}
    modal = _modal_conservative(per_run)
    agreement = distribution.get(modal.value, 0) / n_runs if n_runs else 0.0

    note = (
        "Instruction judging runs once; per-run verdict variation reflects only "
        "the judged-dimension scores. A run with a judge error on any evaluable "
        "judged dimension is counted as 'Unresolved'."
    )
    return VerdictStabilityResult(
        per_run_verdicts=[v.value for v in per_run],
        modal_verdict=modal.value,
        distribution=distribution,
        agreement_fraction=round(agreement, 4),
        note=note,
    )


def stability_for_item(
    rubric: Rubric,
    item_result: ItemResult,
    runs_by_dim: dict[str, list[JudgeRunResult]],
    n_runs: int,
) -> VerdictStabilityResult | None:
    if not runs_by_dim:
        return None
    return compute_verdict_stability(rubric, item_result.dimensions, runs_by_dim, n_runs)
