"""Verdict engine truth table."""

from __future__ import annotations

import pytest

from rubric_eval.models import Rubric
from rubric_eval.results import (
    DimensionResult,
    DimensionStatus,
    GateResult,
    GateStatus,
    InstructionResult,
    InstructionStatus,
    Verdict,
)
from rubric_eval.scoring import compute_verdict, indicative_score


def _rubric(**verdict_kw) -> Rubric:
    data = {
        "id": "r",
        "title": "t",
        "scale": {"min": 1, "max": 5},
        "dimensions": [
            {"id": "gate", "type": "gate"},
            {
                "id": "safety",
                "type": "deterministic",
                "rules": [{"name": "no_refund", "kind": "forbidden_substring", "value": "refund"}],
            },
            {"id": "faithfulness", "type": "reference_grounded", "anchors": {1: "a", 5: "b"}},
            {"id": "clarity", "type": "judged", "anchors": {1: "a", 5: "b"}},
        ],
    }
    if verdict_kw:
        data["verdict"] = verdict_kw
    return Rubric.model_validate(data)


def _gate_dim(status: GateStatus) -> DimensionResult:
    return DimensionResult(
        dimension_id="gate",
        type="gate",
        status=DimensionStatus.EVALUATED,
        gate=GateResult(
            dimension_id="gate",
            status=status,
            instructions=[
                InstructionResult(
                    text="x",
                    method="judge",
                    status=(
                        InstructionStatus.FAIL
                        if status is GateStatus.FAIL
                        else InstructionStatus.PASS
                    ),
                )
            ],
        ),
    )


def _det_dim(passed: bool, dim_id: str = "safety") -> DimensionResult:
    return DimensionResult(
        dimension_id=dim_id,
        type="deterministic",
        status=DimensionStatus.EVALUATED,
        deterministic_passed=passed,
        checks=[],
    )


def _judged(
    dim_id: str,
    *,
    mean: float | None,
    status=DimensionStatus.EVALUATED,
    reason: str | None = None,
    dtype="judged",
) -> DimensionResult:
    return DimensionResult(
        dimension_id=dim_id,
        type=dtype,
        status=status,
        not_evaluated_reason=reason,
        mean=mean,
        scores=[int(mean)] if mean is not None else [],
    )


class TestGates:
    def test_gate_fail_is_fail(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.FAIL),
                _det_dim(True),
                _judged("faithfulness", mean=5, dtype="reference_grounded"),
                _judged("clarity", mean=5),
            ],
        )
        assert v.verdict is Verdict.FAIL
        assert "gate failed" in v.capped_by[0]

    def test_gate_pending_is_unresolved(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PENDING),
                _det_dim(True),
                _judged(
                    "faithfulness",
                    mean=None,
                    status=DimensionStatus.PENDING_JUDGE,
                    dtype="reference_grounded",
                ),
                _judged("clarity", mean=None, status=DimensionStatus.PENDING_JUDGE),
            ],
        )
        assert v.verdict is Verdict.UNRESOLVED

    def test_judged_pending_is_unresolved(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(True),
                _judged(
                    "faithfulness",
                    mean=None,
                    status=DimensionStatus.PENDING_JUDGE,
                    dtype="reference_grounded",
                ),
                _judged("clarity", mean=4.0),
            ],
        )
        assert v.verdict is Verdict.UNRESOLVED
        assert "faithfulness" in v.unresolved_dimensions


class TestResolvedScoring:
    def test_high_means_excellent(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(True),
                _judged("faithfulness", mean=5.0, dtype="reference_grounded"),
                _judged("clarity", mean=4.5),
            ],
        )
        assert v.verdict is Verdict.EXCELLENT
        assert v.judged_mean == pytest.approx(4.75)

    def test_mid_means_acceptable(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(True),
                _judged("faithfulness", mean=3.0, dtype="reference_grounded"),
                _judged("clarity", mean=3.5),
            ],
        )
        assert v.verdict is Verdict.ACCEPTABLE

    def test_low_means_needs_work(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(True),
                _judged("faithfulness", mean=2.6, dtype="reference_grounded"),
                _judged("clarity", mean=2.6),
            ],
        )
        assert v.verdict is Verdict.NEEDS_WORK

    def test_below_floor_caps_even_if_mean_high(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(True),
                _judged("faithfulness", mean=2.0, dtype="reference_grounded"),  # below 2.5 floor
                _judged("clarity", mean=5.0),
            ],
        )
        assert v.verdict is Verdict.NEEDS_WORK
        assert any("needs-work floor" in c for c in v.capped_by)

    def test_deterministic_fail_caps_to_needs_work(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(False),
                _judged("faithfulness", mean=5.0, dtype="reference_grounded"),
                _judged("clarity", mean=5.0),
            ],
        )
        assert v.verdict is Verdict.NEEDS_WORK
        assert v.deterministic_all_passed is False


class TestNotEvaluated:
    def test_not_evaluated_is_not_zero(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(True),
                _judged(
                    "faithfulness",
                    mean=None,
                    status=DimensionStatus.NOT_EVALUATED,
                    reason="no reference",
                    dtype="reference_grounded",
                ),
                _judged("clarity", mean=3.8),
            ],
        )
        # mean is just clarity (3.8) -> Acceptable. A zero for faithfulness would
        # have pulled the mean to 1.9 -> Needs work.
        assert v.verdict is Verdict.ACCEPTABLE
        assert v.judged_mean == pytest.approx(3.8)
        assert "faithfulness" in v.not_evaluated_dimensions
        assert any("NOT scored as zero" in n for n in v.notes)

    def test_all_judged_not_evaluated_gives_acceptable_when_gates_pass(self):
        r = _rubric()
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(True),
                _judged(
                    "faithfulness",
                    mean=None,
                    status=DimensionStatus.NOT_EVALUATED,
                    reason="x",
                    dtype="reference_grounded",
                ),
                _judged("clarity", mean=None, status=DimensionStatus.NOT_EVALUATED, reason="x"),
            ],
        )
        assert v.verdict is Verdict.ACCEPTABLE
        assert v.judged_mean is None


class TestSafety:
    def test_safety_fail_needs_work_by_default(self):
        r = _rubric(safety_dimension_ids=["safety"])
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(False, "safety"),
                _judged("faithfulness", mean=5.0, dtype="reference_grounded"),
                _judged("clarity", mean=5.0),
            ],
        )
        assert v.verdict is Verdict.NEEDS_WORK
        assert any("safety dimension" in c for c in v.capped_by)

    def test_safety_fail_can_force_fail(self):
        r = _rubric(safety_dimension_ids=["safety"], safety_failure_verdict="fail")
        v = compute_verdict(
            r,
            [
                _gate_dim(GateStatus.PASS),
                _det_dim(False, "safety"),
                _judged("faithfulness", mean=5.0, dtype="reference_grounded"),
                _judged("clarity", mean=5.0),
            ],
        )
        assert v.verdict is Verdict.FAIL


class TestIndicativeScore:
    def test_indicative_is_mean_of_evaluated(self):
        dims = [
            _judged("faithfulness", mean=4.0, dtype="reference_grounded"),
            _judged("clarity", mean=5.0),
            _judged("relevance", mean=None, status=DimensionStatus.NOT_EVALUATED, reason="x"),
        ]
        assert indicative_score(dims) == pytest.approx(4.5)

    def test_indicative_none_when_nothing_evaluated(self):
        assert indicative_score([_det_dim(True)]) is None
