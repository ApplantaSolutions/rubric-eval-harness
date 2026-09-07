"""Full evaluate_item pipeline: deterministic + judged + evidence + resilience.

All offline via MockProvider.
"""

from __future__ import annotations

from rubric_eval.dataset import EvalItem
from rubric_eval.evaluate import evaluate_item, safe_evaluate_item
from rubric_eval.models import Rubric
from rubric_eval.providers.mock import MockProvider
from rubric_eval.results import DimensionStatus, GateStatus, Verdict

REF = (
    "The Northwind Widgets quarterly review states that unit sales rose nine percent "
    "and that the Ferndale plant returned to full capacity in August."
)


def _rubric(**over) -> Rubric:
    data = {
        "id": "sumq",
        "title": "Summary quality",
        "scale": {"min": 1, "max": 5},
        "reliability": {"runs_default": 5},
        "dimensions": [
            {
                "id": "gate",
                "type": "gate",
                "global_checks": [
                    {
                        "text": "at most 40 words",
                        "method": "deterministic",
                        "rule": {"name": "w", "kind": "max_word_count", "value": 40},
                    },
                    {"text": "no opinion", "method": "judge"},
                ],
            },
            {
                "id": "format",
                "type": "deterministic",
                "rules": [{"name": "h", "kind": "forbidden_regex", "pattern": r"(?m)^\s*#"}],
            },
            {
                "id": "faithfulness",
                "type": "reference_grounded",
                "anchors": {1: "unsupported", 3: "mostly", 5: "fully supported"},
            },
            {"id": "clarity", "type": "judged", "anchors": {1: "unclear", 5: "clear"}},
        ],
    }
    data.update(over)
    return Rubric.model_validate(data)


def _item(**over) -> EvalItem:
    base = {
        "id": "q1",
        "task": "Summarize the review in two sentences.",
        "candidate_response": "Unit sales rose nine percent. The Ferndale plant returned to full capacity in August.",
        "instructions": ["Two sentences or fewer"],
        "reference": REF,
    }
    base.update(over)
    return EvalItem(**base)


def _by_id(result):
    return {d.dimension_id: d for d in result.dimensions}


class TestHappyPath:
    def test_reference_grounded_success(self):
        judgments = {
            "q1::__gate__": {
                "results": [
                    {
                        "index": 0,
                        "status": "pass",
                        "rationale": "two sentences",
                        "evidence_quote": "",
                    },
                    {
                        "index": 1,
                        "status": "pass",
                        "rationale": "no opinion words",
                        "evidence_quote": "",
                    },
                ]
            },
            "q1::faithfulness": {
                "score": 5,
                "rationale": "every claim is in the reference",
                "evidence_quote": "unit sales rose nine percent",
            },
            "q1::clarity": {"score": 5, "rationale": "very clear", "evidence_quote": ""},
        }
        res = evaluate_item(_rubric(), _item(), MockProvider(judgments), runs=5)
        dims = _by_id(res)
        assert dims["gate"].gate.status is GateStatus.PASS
        assert dims["faithfulness"].status is DimensionStatus.EVALUATED
        assert dims["faithfulness"].mean == 5.0
        assert dims["faithfulness"].evidence_all_verified is True
        assert dims["faithfulness"].evidence_any_unverified is False
        assert res.verdict.verdict is Verdict.EXCELLENT
        assert res.verdict_stability.agreement_fraction == 1.0
        assert res.errors == []
        assert len(dims["faithfulness"].runs) == 5  # every run retained


class TestInstructionGate:
    def test_judged_instruction_fail_fails_gate(self):
        judgments = {
            "q1::__gate__": {
                "results": [
                    {"index": 0, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                    {
                        "index": 1,
                        "status": "fail",
                        "rationale": "editorialises",
                        "evidence_quote": "",
                    },
                ]
            },
            "q1::faithfulness": {
                "score": 5,
                "rationale": "ok",
                "evidence_quote": "unit sales rose nine percent",
            },
            "q1::clarity": {"score": 5, "rationale": "ok", "evidence_quote": ""},
        }
        res = evaluate_item(_rubric(), _item(), MockProvider(judgments), runs=3)
        assert _by_id(res)["gate"].gate.status is GateStatus.FAIL
        assert res.verdict.verdict is Verdict.FAIL

    def test_deterministic_fail_not_rescued_by_judged_pass(self):
        long_item = _item(candidate_response="word " * 45)  # 45 words > 40
        judgments = {
            "q1::__gate__": {
                "results": [
                    {"index": 0, "status": "pass", "rationale": "sure", "evidence_quote": ""},
                    {"index": 1, "status": "pass", "rationale": "sure", "evidence_quote": ""},
                ]
            },
        }
        res = evaluate_item(_rubric(), long_item, MockProvider(judgments), runs=2)
        gate = _by_id(res)["gate"].gate
        assert gate.status is GateStatus.FAIL
        # the deterministic instruction is the one that failed
        assert any(
            i.status.value == "fail" and i.method.value == "deterministic"
            for i in gate.instructions
        )
        assert res.verdict.verdict is Verdict.FAIL

    def test_instruction_provider_error_makes_gate_error(self):
        judgments = {"q1::__gate__": {"error": "rate limited"}}
        res = evaluate_item(_rubric(), _item(), MockProvider(judgments), runs=2)
        assert _by_id(res)["gate"].gate.status is GateStatus.ERROR
        assert res.verdict.verdict is Verdict.UNRESOLVED
        assert any("provider error" in e for e in res.errors)


class TestEvidence:
    def _run(self, faith_entry):
        judgments = {
            "q1::__gate__": {
                "results": [
                    {"index": 0, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                    {"index": 1, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                ]
            },
            "q1::faithfulness": faith_entry,
            "q1::clarity": {"score": 4, "rationale": "ok", "evidence_quote": ""},
        }
        return evaluate_item(_rubric(), _item(), MockProvider(judgments), runs=3)

    def test_exact_evidence_verified(self):
        res = self._run(
            {"score": 5, "rationale": "ok", "evidence_quote": "unit sales rose nine percent"}
        )
        d = _by_id(res)["faithfulness"]
        assert d.evidence_all_verified is True
        assert d.runs[0].evidence.method == "exact"
        assert d.mean == 5.0  # score retained

    def test_normalized_evidence_verified(self):
        res = self._run(
            {"score": 5, "rationale": "ok", "evidence_quote": "  Unit   sales rose nine percent  "}
        )
        d = _by_id(res)["faithfulness"]
        assert d.runs[0].evidence.verified is True
        assert d.runs[0].evidence.method == "normalized"

    def test_hallucinated_evidence_flagged_but_score_kept(self):
        res = self._run(
            {
                "score": 5,
                "rationale": "confident",
                "evidence_quote": "unit sales rose forty percent",
            }
        )
        d = _by_id(res)["faithfulness"]
        assert d.status is DimensionStatus.EVALUATED
        assert d.mean == 5.0  # judge score preserved, NOT zeroed
        assert d.evidence_any_unverified is True
        assert d.runs[0].evidence.method == "not_found"
        assert "fabricated" in d.runs[0].evidence.note

    def test_empty_evidence_marked_empty(self):
        res = self._run({"score": 3, "rationale": "partial", "evidence_quote": ""})
        d = _by_id(res)["faithfulness"]
        assert d.runs[0].evidence.method == "empty"
        assert d.evidence_all_verified is False

    def test_reference_missing_makes_faithfulness_not_evaluated(self):
        item = _item(reference=None)
        judgments = {
            "q1::__gate__": {
                "results": [
                    {"index": 0, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                    {"index": 1, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                ]
            },
            "q1::clarity": {"score": 4, "rationale": "ok", "evidence_quote": ""},
        }
        res = evaluate_item(_rubric(), item, MockProvider(judgments), runs=3)
        d = _by_id(res)["faithfulness"]
        assert d.status is DimensionStatus.NOT_EVALUATED
        assert "requires a reference passage" in d.not_evaluated_reason
        assert d.runs == []  # judge never called for it


class TestConsistencyIntegration:
    def test_per_run_variation_aggregated(self):
        judgments = {
            "q1::__gate__": {
                "results": [
                    {"index": 0, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                    {"index": 1, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                ]
            },
            "q1::faithfulness": {
                "per_run": [
                    {
                        "score": 5,
                        "rationale": "r",
                        "evidence_quote": "unit sales rose nine percent",
                    },
                    {
                        "score": 3,
                        "rationale": "r",
                        "evidence_quote": "unit sales rose nine percent",
                    },
                    {
                        "score": 5,
                        "rationale": "r",
                        "evidence_quote": "unit sales rose nine percent",
                    },
                    {
                        "score": 3,
                        "rationale": "r",
                        "evidence_quote": "unit sales rose nine percent",
                    },
                    {
                        "score": 5,
                        "rationale": "r",
                        "evidence_quote": "unit sales rose nine percent",
                    },
                ]
            },
            "q1::clarity": {"score": 4, "rationale": "ok", "evidence_quote": ""},
        }
        res = evaluate_item(_rubric(), _item(), MockProvider(judgments), runs=5)
        d = _by_id(res)["faithfulness"]
        assert d.scores == [5, 3, 5, 3, 5]
        assert d.minimum == 3 and d.maximum == 5
        assert d.reliability_label.value in ("some_variance", "unreliable")
        assert len(d.runs) == 5


class TestFailureResilience:
    def _judgments_with_faith(self, faith):
        return {
            "q1::__gate__": {
                "results": [
                    {"index": 0, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                    {"index": 1, "status": "pass", "rationale": "ok", "evidence_quote": ""},
                ]
            },
            "q1::faithfulness": faith,
            "q1::clarity": {"score": 4, "rationale": "ok", "evidence_quote": ""},
        }

    def test_provider_error_on_one_run_scored_from_the_rest(self):
        faith = {
            "per_run": [
                {"score": 5, "rationale": "r", "evidence_quote": "unit sales rose nine percent"},
                {"error": "timeout"},
                {"score": 5, "rationale": "r", "evidence_quote": "unit sales rose nine percent"},
                {"score": 4, "rationale": "r", "evidence_quote": "unit sales rose nine percent"},
                {"score": 5, "rationale": "r", "evidence_quote": "unit sales rose nine percent"},
            ]
        }
        res = evaluate_item(
            _rubric(), _item(), MockProvider(self._judgments_with_faith(faith)), runs=5
        )
        d = _by_id(res)["faithfulness"]
        assert d.status is DimensionStatus.EVALUATED
        assert d.judge_error_count == 1
        assert d.scores == [5, 5, 4, 5]
        assert any("judge run(s) failed" in e for e in res.errors)

    def test_all_runs_fail_no_invented_mean(self):
        faith = {"per_run": [{"error": "down"}] * 5}
        res = evaluate_item(
            _rubric(), _item(), MockProvider(self._judgments_with_faith(faith)), runs=5
        )
        d = _by_id(res)["faithfulness"]
        assert d.status is DimensionStatus.NOT_EVALUATED
        assert d.mean is None
        assert "all 5 judge run(s) failed" in d.not_evaluated_reason
        assert d.judge_error_count == 5
        # verdict still computed from the other judged dimension; not zeroed
        assert res.verdict.verdict is not Verdict.FAIL
        assert "faithfulness" in res.verdict.not_evaluated_dimensions

    def test_malformed_then_malformed_is_judge_error(self):
        faith = {"per_run": [{"per_attempt": [{"raw": "junk"}, {"raw": "still junk"}]}] * 3}
        res = evaluate_item(
            _rubric(), _item(), MockProvider(self._judgments_with_faith(faith)), runs=3
        )
        d = _by_id(res)["faithfulness"]
        assert d.status is DimensionStatus.NOT_EVALUATED
        assert d.judge_error_count == 3
        assert d.runs[0].error is not None

    def test_malformed_then_valid_retry_succeeds(self):
        faith = {
            "per_run": [
                {
                    "per_attempt": [
                        {"raw": "not json"},
                        {
                            "score": 4,
                            "rationale": "ok",
                            "evidence_quote": "unit sales rose nine percent",
                        },
                    ]
                }
            ]
            * 3
        }
        res = evaluate_item(
            _rubric(), _item(), MockProvider(self._judgments_with_faith(faith)), runs=3
        )
        d = _by_id(res)["faithfulness"]
        assert d.status is DimensionStatus.EVALUATED
        assert d.scores == [4, 4, 4]

    def test_batch_continues_past_a_broken_item(self):
        good = _item(id="good")
        bad = _item(id="bad")
        judgments = {
            "good::__gate__": {
                "results": [
                    {"index": 0, "status": "pass", "rationale": "ok"},
                    {"index": 1, "status": "pass", "rationale": "ok"},
                ]
            },
            "good::faithfulness": {
                "score": 5,
                "rationale": "ok",
                "evidence_quote": "unit sales rose nine percent",
            },
            "good::clarity": {"score": 5, "rationale": "ok", "evidence_quote": ""},
            "bad::__gate__": {"error": "boom"},
            "bad::faithfulness": {"error": "boom"},
            "bad::clarity": {"error": "boom"},
        }
        provider = MockProvider(judgments)
        results = [safe_evaluate_item(_rubric(), it, provider, runs=2) for it in (good, bad)]
        assert results[0].verdict.verdict is Verdict.EXCELLENT
        assert results[1].verdict.verdict is Verdict.UNRESOLVED
        assert results[1].errors  # bad item recorded its failure, batch survived
