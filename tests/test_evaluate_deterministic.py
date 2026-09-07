"""End-to-end deterministic assembly (no judge layer)."""

from __future__ import annotations

from rubric_eval.dataset import EvalItem
from rubric_eval.evaluate import evaluate_item_deterministic
from rubric_eval.models import Rubric
from rubric_eval.results import DimensionStatus, Verdict


def _rubric() -> Rubric:
    return Rubric.model_validate(
        {
            "id": "r",
            "title": "t",
            "scale": {"min": 1, "max": 5},
            "dimensions": [
                {
                    "id": "gate",
                    "type": "gate",
                    "global_checks": [
                        {
                            "text": "<= 20 words",
                            "method": "deterministic",
                            "rule": {"name": "w", "kind": "max_word_count", "value": 20},
                        }
                    ],
                },
                {
                    "id": "format",
                    "type": "deterministic",
                    "rules": [{"name": "h", "kind": "forbidden_regex", "pattern": r"(?m)^\s*#"}],
                },
                {"id": "faithfulness", "type": "reference_grounded", "anchors": {1: "a", 5: "b"}},
                {"id": "completeness", "type": "spec_grounded", "anchors": {1: "a", 5: "b"}},
                {"id": "clarity", "type": "judged", "anchors": {1: "a", 5: "b"}},
            ],
        }
    )


def test_deterministic_pass_with_reference_leaves_judged_pending():
    item = EvalItem(
        id="i",
        task="summarize",
        candidate_response="A short clean summary of the passage.",
        instructions=["stay neutral"],
        reference="the passage text",
        required_points=["the main point"],
    )
    result = evaluate_item_deterministic(_rubric(), item)
    by_id = {d.dimension_id: d for d in result.dimensions}
    assert by_id["format"].deterministic_passed is True
    assert by_id["faithfulness"].status is DimensionStatus.PENDING_JUDGE
    assert by_id["completeness"].status is DimensionStatus.PENDING_JUDGE
    assert by_id["clarity"].status is DimensionStatus.PENDING_JUDGE
    # gate has a pending item-instruction -> whole verdict Unresolved
    assert result.verdict.verdict is Verdict.UNRESOLVED
    assert result.indicative_score is None


def test_missing_reference_marks_faithfulness_not_evaluated():
    item = EvalItem(
        id="i",
        task="answer",
        candidate_response="An answer.",
        # no reference, no required_points
    )
    result = evaluate_item_deterministic(_rubric(), item)
    by_id = {d.dimension_id: d for d in result.dimensions}
    assert by_id["faithfulness"].status is DimensionStatus.NOT_EVALUATED
    assert "requires a reference passage" in by_id["faithfulness"].not_evaluated_reason
    assert by_id["completeness"].status is DimensionStatus.NOT_EVALUATED
    # clarity has no evidence requirement -> still pending judge
    assert by_id["clarity"].status is DimensionStatus.PENDING_JUDGE


def test_deterministic_length_violation_fails_gate():
    long_response = "word " * 40
    item = EvalItem(id="i", task="t", candidate_response=long_response, reference="ref")
    result = evaluate_item_deterministic(_rubric(), item)
    assert result.verdict.verdict is Verdict.FAIL
