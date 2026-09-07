"""Judge prompt construction, output parsing, and the single corrective retry."""

from __future__ import annotations

import json

import pytest

from rubric_eval.dataset import EvalItem
from rubric_eval.errors import JudgeParseError, ProviderError
from rubric_eval.judge import (
    build_dimension_prompt,
    build_instruction_prompt,
    call_judge,
    extract_json_object,
    parse_dimension_judgment,
    parse_instruction_judgments,
)
from rubric_eval.models import Rubric, Scale

SCALE = Scale(min=1, max=5)


def _rubric() -> Rubric:
    return Rubric.model_validate(
        {
            "id": "r",
            "title": "t",
            "scale": {"min": 1, "max": 5},
            "dimensions": [
                {
                    "id": "faithfulness",
                    "type": "reference_grounded",
                    "anchors": {1: "unsupported", 3: "mostly", 5: "fully supported"},
                },
                {"id": "clarity", "type": "judged", "anchors": {1: "unclear", 5: "clear"}},
            ],
        }
    )


def _item(**kw) -> EvalItem:
    base = {
        "id": "i",
        "task": "Summarize the passage.",
        "candidate_response": "A short summary.",
        "reference": "The passage says growth was five percent.",
        "instructions": ["Two sentences or fewer", "Neutral tone"],
    }
    base.update(kw)
    return EvalItem(**base)


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #


class TestExtraction:
    def test_plain_json(self):
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        text = 'Here is my answer:\n```json\n{"a": 1}\n```\n'
        assert extract_json_object(text) == {"a": 1}

    def test_surrounding_prose(self):
        text = 'Sure! {"a": 1, "b": "x"} — hope that helps.'
        assert extract_json_object(text) == {"a": 1, "b": "x"}

    def test_json_with_braces_in_strings(self):
        text = 'prefix {"a": "has } brace", "b": 2} suffix'
        assert extract_json_object(text) == {"a": "has } brace", "b": 2}

    def test_no_json_raises(self):
        with pytest.raises(JudgeParseError, match="could not parse"):
            extract_json_object("there is no json here")

    def test_json_array_rejected(self):
        with pytest.raises(JudgeParseError):
            extract_json_object("[1, 2, 3]")


# --------------------------------------------------------------------------- #
# Dimension judgment parsing
# --------------------------------------------------------------------------- #


class TestDimensionParsing:
    def test_valid(self):
        j = parse_dimension_judgment(
            '{"score": 4, "rationale": "good", "evidence_quote": "five percent"}', SCALE
        )
        assert j.score == 4
        assert j.evidence_quote == "five percent"

    def test_valid_missing_evidence_defaults_empty(self):
        j = parse_dimension_judgment('{"score": 3, "rationale": "ok"}', SCALE)
        assert j.evidence_quote == ""

    def test_integral_float_score_accepted(self):
        assert parse_dimension_judgment('{"score": 4.0, "rationale": "ok"}', SCALE).score == 4

    def test_non_integral_float_rejected(self):
        with pytest.raises(JudgeParseError, match="must be an integer"):
            parse_dimension_judgment('{"score": 4.5, "rationale": "ok"}', SCALE)

    def test_string_score_rejected(self):
        with pytest.raises(JudgeParseError, match="must be a number"):
            parse_dimension_judgment('{"score": "4", "rationale": "ok"}', SCALE)

    def test_boolean_score_rejected(self):
        with pytest.raises(JudgeParseError, match="boolean"):
            parse_dimension_judgment('{"score": true, "rationale": "ok"}', SCALE)

    def test_score_above_scale_rejected(self):
        with pytest.raises(JudgeParseError, match="outside the rubric scale"):
            parse_dimension_judgment('{"score": 7, "rationale": "ok"}', SCALE)

    def test_score_below_scale_rejected(self):
        with pytest.raises(JudgeParseError, match="outside the rubric scale"):
            parse_dimension_judgment('{"score": 0, "rationale": "ok"}', SCALE)

    def test_missing_score_rejected(self):
        with pytest.raises(JudgeParseError, match="missing required field 'score'"):
            parse_dimension_judgment('{"rationale": "ok"}', SCALE)

    def test_missing_rationale_rejected(self):
        with pytest.raises(JudgeParseError, match="missing required field 'rationale'"):
            parse_dimension_judgment('{"score": 3}', SCALE)

    def test_empty_rationale_rejected(self):
        with pytest.raises(JudgeParseError, match="must not be empty"):
            parse_dimension_judgment('{"score": 3, "rationale": "  "}', SCALE)

    def test_wrong_type_rationale_rejected(self):
        with pytest.raises(JudgeParseError, match="must be a string"):
            parse_dimension_judgment('{"score": 3, "rationale": 5}', SCALE)


# --------------------------------------------------------------------------- #
# Instruction judgment parsing
# --------------------------------------------------------------------------- #


class TestInstructionParsing:
    def test_valid(self):
        text = json.dumps(
            {
                "results": [
                    {"index": 0, "status": "pass", "rationale": "ok"},
                    {"index": 1, "status": "fail", "rationale": "too long"},
                ]
            }
        )
        out = parse_instruction_judgments(text, 2)
        assert [o.passed for o in out] == [True, False]

    def test_reordered_indices_sorted(self):
        text = json.dumps(
            {
                "results": [
                    {"index": 1, "status": "pass", "rationale": "b"},
                    {"index": 0, "status": "fail", "rationale": "a"},
                ]
            }
        )
        out = parse_instruction_judgments(text, 2)
        assert [o.index for o in out] == [0, 1]
        assert out[0].passed is False

    def test_count_mismatch_rejected(self):
        text = json.dumps({"results": [{"index": 0, "status": "pass", "rationale": "x"}]})
        with pytest.raises(JudgeParseError, match="expected 2"):
            parse_instruction_judgments(text, 2)

    def test_bad_status_rejected(self):
        text = json.dumps({"results": [{"index": 0, "status": "maybe", "rationale": "x"}]})
        with pytest.raises(JudgeParseError, match="'pass' or 'fail'"):
            parse_instruction_judgments(text, 1)

    def test_out_of_range_index_rejected(self):
        text = json.dumps({"results": [{"index": 3, "status": "pass", "rationale": "x"}]})
        with pytest.raises(JudgeParseError, match="out of range"):
            parse_instruction_judgments(text, 1)

    def test_missing_results_rejected(self):
        with pytest.raises(JudgeParseError, match="'results'"):
            parse_instruction_judgments('{"foo": 1}', 1)


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #


class TestPrompts:
    def test_reference_grounded_prompt_has_reference_and_rules(self):
        r = _rubric()
        dim = next(d for d in r.dimensions if d.id == "faithfulness")
        system, user = build_dimension_prompt(r, dim, _item())
        assert "ONLY against the SUPPLIED REFERENCE" in system
        assert "do not invent a quotation" in system
        assert "SUPPLIED REFERENCE" in user
        assert "growth was five percent" in user

    def test_plain_judged_prompt_has_no_reference_block(self):
        r = _rubric()
        dim = next(d for d in r.dimensions if d.id == "clarity")
        system, user = build_dimension_prompt(r, dim, _item())
        assert "SUPPLIED REFERENCE" not in user
        assert "outside knowledge" not in system

    def test_dimension_prompt_lists_anchors(self):
        r = _rubric()
        dim = next(d for d in r.dimensions if d.id == "faithfulness")
        _, user = build_dimension_prompt(r, dim, _item())
        assert "5 = fully supported" in user
        assert "1 = unsupported" in user

    def test_instruction_prompt_numbers_instructions(self):
        _, user = build_instruction_prompt(_item(), ["A", "B", "C"])
        assert "0. A" in user
        assert "2. C" in user


# --------------------------------------------------------------------------- #
# call_judge: one corrective retry
# --------------------------------------------------------------------------- #


class _ScriptedProvider:
    """Returns a preset list of responses, one per call. Raises if exhausted."""

    name = "scripted"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, *, system, user, temperature, max_tokens=1024, metadata=None):
        if self.calls >= len(self._responses):
            raise AssertionError("scripted provider ran out of responses")
        resp = self._responses[self.calls]
        self.calls += 1
        if isinstance(resp, Exception):
            raise resp
        return resp


def _parse(text):
    return parse_dimension_judgment(text, SCALE)


def test_call_judge_valid_first_try():
    p = _ScriptedProvider(['{"score": 4, "rationale": "ok"}'])
    result = call_judge(p, system="s", user="u", parse=_parse, temperature=0.0)
    assert result.parsed.score == 4
    assert result.attempts == 1
    assert p.calls == 1


def test_call_judge_malformed_then_valid_retry():
    p = _ScriptedProvider(["not json at all", '{"score": 2, "rationale": "ok"}'])
    result = call_judge(p, system="s", user="u", parse=_parse, temperature=0.0)
    assert result.parsed.score == 2
    assert result.attempts == 2
    assert p.calls == 2


def test_call_judge_malformed_twice_records_judge_error():
    p = _ScriptedProvider(["garbage one", "garbage two"])
    result = call_judge(p, system="s", user="u", parse=_parse, temperature=0.0)
    assert result.parsed is None
    assert result.error is not None
    assert "after retry" in result.error
    assert p.calls == 2


def test_call_judge_provider_error_propagates_without_retry():
    p = _ScriptedProvider([ProviderError("boom")])
    with pytest.raises(ProviderError, match="boom"):
        call_judge(p, system="s", user="u", parse=_parse, temperature=0.0)
    assert p.calls == 1


def test_call_judge_retry_prompt_mentions_the_error():
    captured = {}

    class Capturing:
        name = "cap"

        def __init__(self):
            self.n = 0

        def complete(self, *, system, user, temperature, max_tokens=1024, metadata=None):
            self.n += 1
            if self.n == 1:
                return "definitely not json"
            captured["retry_user"] = user
            return '{"score": 3, "rationale": "ok"}'

    call_judge(Capturing(), system="s", user="ORIGINAL", parse=_parse, temperature=0.0)
    assert "ORIGINAL" in captured["retry_user"]
    assert "COULD NOT BE PARSED" in captured["retry_user"]
