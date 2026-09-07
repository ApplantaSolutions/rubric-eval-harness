"""Deterministic check engine."""

from __future__ import annotations

import pytest

from rubric_eval.checks.deterministic import (
    apply_rule,
    count_sentences,
    count_words,
    run_deterministic_dimension,
)
from rubric_eval.models import Dimension, Rule
from rubric_eval.results import CheckOutcome


class TestCounts:
    def test_count_words(self):
        assert count_words("one two three") == 3
        assert count_words("  spaced   out  ") == 2
        assert count_words("") == 0

    def test_count_sentences_basic(self):
        assert count_sentences("One. Two. Three.") == 3
        assert count_sentences("Is it? Yes! Ok.") == 3

    def test_count_sentences_no_terminal_punct_is_one(self):
        assert count_sentences("a statement with no period") == 1

    def test_count_sentences_empty_is_zero(self):
        assert count_sentences("   ") == 0

    def test_count_sentences_ellipsis_groups(self):
        assert count_sentences("Well... that happened.") == 2


def _rule(**kw) -> Rule:
    return Rule(**kw)


class TestWordCountRules:
    def test_max_word_count_pass(self):
        r = apply_rule(_rule(name="w", kind="max_word_count", value=5), "a b c")
        assert r.outcome is CheckOutcome.PASS

    def test_max_word_count_fail(self):
        r = apply_rule(_rule(name="w", kind="max_word_count", value=2), "a b c")
        assert r.outcome is CheckOutcome.FAIL
        assert "3 words" in r.observed

    def test_min_word_count_boundary(self):
        r = apply_rule(_rule(name="w", kind="min_word_count", value=3), "a b c")
        assert r.outcome is CheckOutcome.PASS
        r2 = apply_rule(_rule(name="w", kind="min_word_count", value=4), "a b c")
        assert r2.outcome is CheckOutcome.FAIL


class TestSentenceRules:
    def test_max_sentences_fail(self):
        r = apply_rule(_rule(name="s", kind="max_sentences", value=2), "One. Two. Three.")
        assert r.outcome is CheckOutcome.FAIL

    def test_min_sentences_pass(self):
        r = apply_rule(_rule(name="s", kind="min_sentences", value=1), "Just one.")
        assert r.outcome is CheckOutcome.PASS


class TestCharRules:
    def test_max_chars(self):
        assert (
            apply_rule(_rule(name="c", kind="max_chars", value=5), "abcde").outcome
            is CheckOutcome.PASS
        )
        assert (
            apply_rule(_rule(name="c", kind="max_chars", value=4), "abcde").outcome
            is CheckOutcome.FAIL
        )

    def test_min_chars(self):
        assert (
            apply_rule(_rule(name="c", kind="min_chars", value=3), "abc").outcome
            is CheckOutcome.PASS
        )


class TestSubstringRules:
    def test_required_substring_present(self):
        r = apply_rule(
            _rule(name="s", kind="required_substring", value="ticket"),
            "your ticket number is 42",
        )
        assert r.outcome is CheckOutcome.PASS

    def test_required_substring_absent_fails(self):
        r = apply_rule(_rule(name="s", kind="required_substring", value="ticket"), "no id here")
        assert r.outcome is CheckOutcome.FAIL

    def test_required_substring_case_insensitive(self):
        r = apply_rule(
            _rule(
                name="s",
                kind="required_substring",
                value="Ticket",
                case_sensitive=False,
            ),
            "your TICKET is ready",
        )
        assert r.outcome is CheckOutcome.PASS

    def test_forbidden_substring(self):
        ok = apply_rule(
            _rule(name="s", kind="forbidden_substring", value="refund"),
            "we can offer a credit",
        )
        assert ok.outcome is CheckOutcome.PASS
        bad = apply_rule(
            _rule(name="s", kind="forbidden_substring", value="refund"),
            "we will refund you",
        )
        assert bad.outcome is CheckOutcome.FAIL


class TestRegexRules:
    def test_forbidden_regex_matches_reports_snippet(self):
        r = apply_rule(
            _rule(name="r", kind="forbidden_regex", pattern=r"(?m)^\s*#"),
            "# Heading\nbody text",
        )
        assert r.outcome is CheckOutcome.FAIL
        assert "matched" in r.observed

    def test_forbidden_regex_no_match_passes(self):
        r = apply_rule(
            _rule(name="r", kind="forbidden_regex", pattern=r"(?m)^\s*#"),
            "no markdown headers here",
        )
        assert r.outcome is CheckOutcome.PASS

    def test_required_regex(self):
        r = apply_rule(
            _rule(name="r", kind="required_regex", pattern=r"\b\d{4}\b"),
            "reference code 2048 applies",
        )
        assert r.outcome is CheckOutcome.PASS


class TestValidJson:
    def test_valid_json_passes(self):
        r = apply_rule(_rule(name="j", kind="valid_json"), '{"a": 1}')
        assert r.outcome is CheckOutcome.PASS

    def test_invalid_json_fails_with_reason(self):
        r = apply_rule(_rule(name="j", kind="valid_json"), "{a: 1")
        assert r.outcome is CheckOutcome.FAIL
        assert "invalid JSON" in r.observed


class TestDimensionRollup:
    def test_all_pass(self):
        dim = Dimension(
            id="fmt",
            type="deterministic",
            rules=[
                Rule(name="w", kind="max_word_count", value=10),
                Rule(name="h", kind="forbidden_regex", pattern=r"(?m)^\s*#"),
            ],
        )
        result = run_deterministic_dimension(dim, "a short clean line")
        assert result.deterministic_passed is True
        assert len(result.checks) == 2

    def test_one_fail_fails_dimension(self):
        dim = Dimension(
            id="fmt",
            type="deterministic",
            rules=[
                Rule(name="w", kind="max_word_count", value=2),
                Rule(name="h", kind="forbidden_regex", pattern=r"(?m)^\s*#"),
            ],
        )
        result = run_deterministic_dimension(dim, "one two three four")
        assert result.deterministic_passed is False


@pytest.mark.parametrize(
    "text,expected",
    [("a. b. c.", 3), ("no punctuation", 1), ("", 0), ("Wait—really? Yes.", 2)],
)
def test_sentence_count_param(text, expected):
    assert count_sentences(text) == expected
