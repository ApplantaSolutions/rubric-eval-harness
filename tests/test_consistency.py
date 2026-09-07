"""N-run aggregation + reliability heuristics."""

from __future__ import annotations

import pytest

from rubric_eval.consistency import (
    aggregate_scores,
    reliability_label,
    summarize_evidence,
)
from rubric_eval.models import ReliabilityConfig
from rubric_eval.results import EvidenceCheck, JudgeRunResult, ReliabilityLabel

CFG = ReliabilityConfig()


def _runs(*scores, errors=0):
    runs = [JudgeRunResult(run_index=i, score=s) for i, s in enumerate(scores)]
    for k in range(errors):
        runs.append(JudgeRunResult(run_index=len(runs), error=f"err {k}"))
    return runs


class TestAggregate:
    def test_basic_stats(self):
        s = aggregate_scores(_runs(4, 5, 4, 4, 3), disagreement_threshold=2)
        assert s.scores == [4, 5, 4, 4, 3]
        assert s.mean == pytest.approx(4.0)
        assert s.minimum == 3
        assert s.maximum == 5
        assert s.n_valid == 5
        assert s.judge_error_count == 0

    def test_population_stdev(self):
        s = aggregate_scores(_runs(2, 4), disagreement_threshold=2)
        # population stdev of [2,4] = 1.0
        assert s.stdev == pytest.approx(1.0)

    def test_zero_variance(self):
        s = aggregate_scores(_runs(3, 3, 3, 3), disagreement_threshold=2)
        assert s.stdev == pytest.approx(0.0)
        assert s.pairwise_disagreement_rate == pytest.approx(0.0)

    def test_pairwise_disagreement_rate(self):
        # scores [1,1,5,5]: pairs = 6; |a-b|>=2 for the 4 cross pairs -> 4/6
        s = aggregate_scores(_runs(1, 1, 5, 5), disagreement_threshold=2)
        assert s.pairwise_disagreement_rate == pytest.approx(4 / 6)

    def test_single_run_stdev_zero(self):
        s = aggregate_scores(_runs(4), disagreement_threshold=2)
        assert s.stdev == pytest.approx(0.0)
        assert s.n_valid == 1

    def test_all_errors_no_stats(self):
        s = aggregate_scores(_runs(errors=3), disagreement_threshold=2)
        assert s.n_valid == 0
        assert s.mean is None
        assert s.stdev is None
        assert s.judge_error_count == 3

    def test_partial_errors_scored_from_valid(self):
        s = aggregate_scores(_runs(4, 4, errors=2), disagreement_threshold=2)
        assert s.n_valid == 2
        assert s.judge_error_count == 2
        assert s.mean == pytest.approx(4.0)

    def test_raw_scores_retained(self):
        runs = _runs(5, 3, 4)
        s = aggregate_scores(runs, disagreement_threshold=2)
        assert s.scores == [5, 3, 4]  # order preserved, nothing discarded


class TestReliabilityLabel:
    def test_single_run_not_applicable(self):
        s = aggregate_scores(_runs(4), disagreement_threshold=2)
        assert reliability_label(s, CFG) is ReliabilityLabel.NOT_APPLICABLE

    def test_zero_variance_is_stable(self):
        s = aggregate_scores(_runs(4, 4, 4, 4, 4), disagreement_threshold=2)
        assert reliability_label(s, CFG) is ReliabilityLabel.STABLE

    def test_small_spread_is_some_variance(self):
        # [4,4,4,4,5] -> pstdev = 0.4 (< low 0.5) BUT disagreement 0 ... stable.
        # [4,4,5,5,5] -> pstdev ~0.49 -> still stable by default heuristic.
        # [3,4,4,4,5] -> pstdev ~0.63 (> low 0.5) -> some_variance
        s = aggregate_scores(_runs(3, 4, 4, 4, 5), disagreement_threshold=2)
        assert reliability_label(s, CFG) is ReliabilityLabel.SOME_VARIANCE

    def test_disagreement_alone_triggers_some_variance(self):
        # [3,5,4,4,4]: pstdev ~0.63 -> some_variance anyway; check a low-stdev
        # disagreement case instead: [4,4,4,4,2] pstdev ~0.8 -> some/unreliable.
        # Use [3,3,3,5]: one pair |3-5|=2 -> disagreement 3/6=0.5 > 0.34 -> unreliable
        s = aggregate_scores(_runs(3, 3, 3, 5), disagreement_threshold=2)
        assert reliability_label(s, CFG) is ReliabilityLabel.UNRELIABLE

    def test_high_stdev_is_unreliable(self):
        s = aggregate_scores(_runs(1, 5, 1, 5, 3), disagreement_threshold=2)
        assert reliability_label(s, CFG) is ReliabilityLabel.UNRELIABLE

    def test_thresholds_are_configurable(self):
        strict = ReliabilityConfig(low_variance_stdev=0.01, high_variance_stdev=0.05)
        s = aggregate_scores(_runs(4, 4, 4, 4, 5), disagreement_threshold=2)
        # pstdev 0.4 > 0.05 -> unreliable under the strict config
        assert reliability_label(s, strict) is ReliabilityLabel.UNRELIABLE
        assert reliability_label(s, CFG) is ReliabilityLabel.STABLE  # default: stable


class TestEvidenceSummary:
    def test_none_when_no_evidence(self):
        out = summarize_evidence(_runs(4, 4))
        assert out == {"evidence_all_verified": None, "evidence_any_unverified": None}

    def test_all_verified(self):
        runs = [
            JudgeRunResult(
                run_index=i,
                score=4,
                evidence=EvidenceCheck(quote="q", verified=True, method="exact"),
            )
            for i in range(3)
        ]
        out = summarize_evidence(runs)
        assert out == {"evidence_all_verified": True, "evidence_any_unverified": False}

    def test_some_unverified(self):
        runs = [
            JudgeRunResult(
                run_index=0,
                score=4,
                evidence=EvidenceCheck(quote="q", verified=True, method="exact"),
            ),
            JudgeRunResult(
                run_index=1,
                score=4,
                evidence=EvidenceCheck(quote="z", verified=False, method="not_found"),
            ),
        ]
        out = summarize_evidence(runs)
        assert out == {"evidence_all_verified": False, "evidence_any_unverified": True}
