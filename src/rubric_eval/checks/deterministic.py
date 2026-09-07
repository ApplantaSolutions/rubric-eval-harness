"""Deterministic checks. No model, no network, fully repeatable.

Text metrics (word / sentence counts) are simple, transparent heuristics.
Their limitations are documented in docs/methodology.md and surfaced in the
report; the synthetic dataset is written so the heuristics are unambiguous.
"""

from __future__ import annotations

import json
import re

from ..models import Dimension, Rule, RuleKind
from ..results import CheckOutcome, CheckResult, DimensionResult, DimensionStatus

_WORD_RE = re.compile(r"\S+")
_SENTENCE_END_RE = re.compile(r"[.!?]+(?=\s|$)")


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def count_sentences(text: str) -> int:
    """Heuristic sentence count: groups of terminal punctuation followed by
    whitespace or end-of-string. Non-empty text with no terminal punctuation
    counts as one sentence.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    n = len(_SENTENCE_END_RE.findall(stripped))
    return n if n > 0 else 1


def count_chars(text: str) -> int:
    return len(text)


def _regex_flags(rule: Rule) -> int:
    return 0 if rule.case_sensitive else re.IGNORECASE


def apply_rule(rule: Rule, response: str) -> CheckResult:  # noqa: C901 - a flat dispatch
    kind = rule.kind

    if kind is RuleKind.MAX_WORD_COUNT:
        actual = count_words(response)
        ok = actual <= int(rule.value)  # type: ignore[arg-type]
        return CheckResult(
            name=rule.name,
            kind=kind.value,
            expected=f"at most {rule.value} words",
            observed=f"{actual} words",
            outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            explanation=(
                f"response has {actual} words; limit is {rule.value}"
                if not ok
                else f"response has {actual} words (within the {rule.value}-word limit)"
            ),
        )

    if kind is RuleKind.MIN_WORD_COUNT:
        actual = count_words(response)
        ok = actual >= int(rule.value)  # type: ignore[arg-type]
        return CheckResult(
            name=rule.name,
            kind=kind.value,
            expected=f"at least {rule.value} words",
            observed=f"{actual} words",
            outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            explanation=f"response has {actual} words; minimum is {rule.value}",
        )

    if kind is RuleKind.MAX_SENTENCES:
        actual = count_sentences(response)
        ok = actual <= int(rule.value)  # type: ignore[arg-type]
        return CheckResult(
            name=rule.name,
            kind=kind.value,
            expected=f"at most {rule.value} sentences",
            observed=f"{actual} sentences",
            outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            explanation=f"response has ~{actual} sentences; limit is {rule.value}",
        )

    if kind is RuleKind.MIN_SENTENCES:
        actual = count_sentences(response)
        ok = actual >= int(rule.value)  # type: ignore[arg-type]
        return CheckResult(
            name=rule.name,
            kind=kind.value,
            expected=f"at least {rule.value} sentences",
            observed=f"{actual} sentences",
            outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            explanation=f"response has ~{actual} sentences; minimum is {rule.value}",
        )

    if kind is RuleKind.MAX_CHARS:
        actual = count_chars(response)
        ok = actual <= int(rule.value)  # type: ignore[arg-type]
        return CheckResult(
            name=rule.name,
            kind=kind.value,
            expected=f"at most {rule.value} characters",
            observed=f"{actual} characters",
            outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            explanation=f"response is {actual} characters; limit is {rule.value}",
        )

    if kind is RuleKind.MIN_CHARS:
        actual = count_chars(response)
        ok = actual >= int(rule.value)  # type: ignore[arg-type]
        return CheckResult(
            name=rule.name,
            kind=kind.value,
            expected=f"at least {rule.value} characters",
            observed=f"{actual} characters",
            outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            explanation=f"response is {actual} characters; minimum is {rule.value}",
        )

    if kind in (RuleKind.REQUIRED_SUBSTRING, RuleKind.FORBIDDEN_SUBSTRING):
        needle = str(rule.value)
        haystack = response
        if not rule.case_sensitive:
            needle = needle.lower()
            haystack = haystack.lower()
        present = needle in haystack
        want_present = kind is RuleKind.REQUIRED_SUBSTRING
        ok = present == want_present
        label = "required" if want_present else "forbidden"
        return CheckResult(
            name=rule.name,
            kind=kind.value,
            expected=f"{label} substring {rule.value!r} "
            f"{'present' if want_present else 'absent'}"
            + ("" if rule.case_sensitive else " (case-insensitive)"),
            observed=f"substring {'present' if present else 'absent'}",
            outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            explanation=(
                f"{label} substring {rule.value!r} was {'present' if present else 'absent'}"
            ),
        )

    if kind in (RuleKind.REQUIRED_REGEX, RuleKind.FORBIDDEN_REGEX):
        pattern = re.compile(str(rule.pattern), _regex_flags(rule))
        match = pattern.search(response)
        want_match = kind is RuleKind.REQUIRED_REGEX
        ok = (match is not None) == want_match
        label = "required" if want_match else "forbidden"
        snippet = ""
        if match is not None:
            text = match.group(0)
            snippet = f" (matched {text[:60]!r})"
        return CheckResult(
            name=rule.name,
            kind=kind.value,
            expected=f"{label} pattern /{rule.pattern}/ "
            f"{'matches' if want_match else 'does not match'}",
            observed=("matched" if match is not None else "no match") + snippet,
            outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            explanation=(
                f"{label} pattern /{rule.pattern}/ "
                f"{'matched' if match is not None else 'did not match'}{snippet}"
            ),
        )

    if kind is RuleKind.VALID_JSON:
        try:
            json.loads(response.strip())
            return CheckResult(
                name=rule.name,
                kind=kind.value,
                expected="response parses as JSON",
                observed="valid JSON",
                outcome=CheckOutcome.PASS,
                explanation="response is valid JSON",
            )
        except json.JSONDecodeError as exc:
            return CheckResult(
                name=rule.name,
                kind=kind.value,
                expected="response parses as JSON",
                observed=f"invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
                outcome=CheckOutcome.FAIL,
                explanation=f"response is not valid JSON: {exc.msg}",
            )

    # Unreachable: Rule validation rejects unknown kinds.
    return CheckResult(
        name=rule.name,
        kind=str(kind),
        expected="(unknown rule kind)",
        observed="(not evaluated)",
        outcome=CheckOutcome.ERROR,
        explanation=f"unsupported rule kind: {kind}",
    )


def run_deterministic_dimension(dim: Dimension, response: str) -> DimensionResult:
    checks = [apply_rule(rule, response) for rule in dim.rules]
    passed = all(c.outcome is CheckOutcome.PASS for c in checks)
    return DimensionResult(
        dimension_id=dim.id,
        type=dim.type,
        status=DimensionStatus.EVALUATED,
        checks=checks,
        deterministic_passed=passed,
    )
