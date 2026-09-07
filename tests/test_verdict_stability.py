"""Verdict stability across N judged runs.

With this rubric (gate + a single judged 'clarity' dimension, default verdict
config: excellent_min_mean=4.0, acceptable_min_mean=3.0, needs_work_floor=2.5)
a single run's clarity score maps to:
    5 or 4 -> Excellent   |   3 -> Acceptable   |   2 or 1 -> Needs work
"""

from __future__ import annotations

from rubric_eval.models import Rubric
from rubric_eval.results import (
    DimensionResult,
    DimensionStatus,
    GateResult,
    GateStatus,
    InstructionResult,
    InstructionStatus,
    JudgeRunResult,
)
from rubric_eval.stability import compute_verdict_stability


def _rubric() -> Rubric:
    return Rubric.model_validate(
        {
            "id": "r",
            "title": "t",
            "scale": {"min": 1, "max": 5},
            "dimensions": [
                {"id": "gate", "type": "gate"},
                {"id": "clarity", "type": "judged", "anchors": {1: "a", 5: "b"}},
            ],
        }
    )


def _gate_pass() -> DimensionResult:
    return DimensionResult(
        dimension_id="gate",
        type="gate",
        status=DimensionStatus.EVALUATED,
        gate=GateResult(
            dimension_id="gate",
            status=GateStatus.PASS,
            instructions=[
                InstructionResult(text="x", method="judge", status=InstructionStatus.PASS)
            ],
        ),
    )


def _clarity() -> DimensionResult:
    return DimensionResult(
        dimension_id="clarity",
        type="judged",
        status=DimensionStatus.EVALUATED,
        mean=3.0,
        scores=[3],
    )


def _run(idx, score=None, error=None):
    return JudgeRunResult(run_index=idx, score=score, error=error)


def _stability(scores_or_errors, n):
    r = _rubric()
    final = [_gate_pass(), _clarity()]
    runs = {
        "clarity": [
            _run(i, score=v) if isinstance(v, int) else _run(i, error=str(v))
            for i, v in enumerate(scores_or_errors)
        ]
    }
    return compute_verdict_stability(r, final, runs, n)


def test_identical_verdicts_full_agreement():
    st = _stability([3, 3, 3, 3, 3], 5)
    assert st.per_run_verdicts == ["Acceptable"] * 5
    assert st.modal_verdict == "Acceptable"
    assert st.agreement_fraction == 1.0


def test_mixed_verdicts_modal_and_distribution():
    st = _stability([3, 3, 3, 5, 3], 5)
    assert st.distribution == {"Acceptable": 4, "Excellent": 1}
    assert st.modal_verdict == "Acceptable"
    assert st.agreement_fraction == 0.8


def test_judge_error_run_is_unresolved():
    st = _stability([3, 3, "boom", 3, 3], 5)
    assert st.per_run_verdicts[2] == "Unresolved"
    assert st.distribution["Unresolved"] == 1
    assert st.modal_verdict == "Acceptable"


def test_tie_resolves_to_more_conservative():
    st = _stability([5, 5, 3, 3], 4)
    assert st.distribution == {"Excellent": 2, "Acceptable": 2}
    assert st.modal_verdict == "Acceptable"  # tie -> lower-ranked verdict wins


def test_unresolved_ties_win_as_most_conservative():
    st = _stability([3, "x"], 2)
    assert st.distribution == {"Acceptable": 1, "Unresolved": 1}
    assert st.modal_verdict == "Unresolved"  # ranked below Fail


def test_note_explains_once_per_run_instruction_judging():
    st = _stability([3, 3, 3], 3)
    assert "Instruction judging runs once" in st.note
