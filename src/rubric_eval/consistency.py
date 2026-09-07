"""N-run aggregation and reliability heuristics.

IMPORTANT: the reliability *label* (STABLE / SOME_VARIANCE / UNRELIABLE) is a
convenience summary derived from CONFIGURABLE OPERATIONAL HEURISTICS
(``ReliabilityConfig``). Those thresholds are NOT statistically validated
boundaries. The raw statistics — every per-run score, the mean, the population
standard deviation, min/max, and the pairwise disagreement rate — are the source
of truth and are always retained on the ``DimensionResult`` and shown in the
report. See docs/methodology.md.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from itertools import combinations

from .models import ReliabilityConfig
from .results import JudgeRunResult, ReliabilityLabel


@dataclass(frozen=True)
class ConsistencyStats:
    scores: list[int] = field(default_factory=list)
    n_runs: int = 0
    n_valid: int = 0
    judge_error_count: int = 0
    mean: float | None = None
    stdev: float | None = None  # population standard deviation
    minimum: int | None = None
    maximum: int | None = None
    pairwise_disagreement_rate: float | None = None


def aggregate_scores(
    runs: list[JudgeRunResult], *, disagreement_threshold: int
) -> ConsistencyStats:
    scores = [r.score for r in runs if r.score is not None]
    errors = sum(1 for r in runs if r.error is not None)

    if not scores:
        return ConsistencyStats(
            scores=[],
            n_runs=len(runs),
            n_valid=0,
            judge_error_count=errors,
        )

    mean = statistics.fmean(scores)
    stdev = statistics.pstdev(scores) if len(scores) > 1 else 0.0

    pairs = list(combinations(scores, 2))
    disagreement = (
        sum(1 for a, b in pairs if abs(a - b) >= disagreement_threshold) / len(pairs)
        if pairs
        else 0.0
    )

    return ConsistencyStats(
        scores=scores,
        n_runs=len(runs),
        n_valid=len(scores),
        judge_error_count=errors,
        mean=mean,
        stdev=stdev,
        minimum=min(scores),
        maximum=max(scores),
        pairwise_disagreement_rate=disagreement,
    )


def reliability_label(stats: ConsistencyStats, cfg: ReliabilityConfig) -> ReliabilityLabel:
    """Map raw statistics to a label using the configured heuristics.

    Not a statistical test — just a reading aid. The raw numbers travel with it.
    """
    if stats.n_valid <= 1 or stats.stdev is None:
        return ReliabilityLabel.NOT_APPLICABLE

    disagreement = stats.pairwise_disagreement_rate or 0.0

    if stats.stdev > cfg.high_variance_stdev or disagreement > cfg.unreliable_disagreement_rate:
        return ReliabilityLabel.UNRELIABLE
    if stats.stdev > cfg.low_variance_stdev or disagreement > 0.0:
        return ReliabilityLabel.SOME_VARIANCE
    return ReliabilityLabel.STABLE


def summarize_evidence(runs: list[JudgeRunResult]) -> dict[str, bool | None]:
    """Roll up per-run evidence checks.

    ``evidence_any_unverified`` means specifically that a run returned a quote
    that is NOT present in the reference (``method == "not_found"``) — the
    "the judge may have fabricated its evidence" signal. An empty quote or a
    missing reference is absence of evidence, not fabrication, and does not set
    this flag (it does leave ``evidence_all_verified`` False).
    """
    checks = [r.evidence for r in runs if r.evidence is not None]
    if not checks:
        return {"evidence_all_verified": None, "evidence_any_unverified": None}
    return {
        "evidence_all_verified": all(c.verified for c in checks),
        "evidence_any_unverified": any(c.method == "not_found" for c in checks),
    }
