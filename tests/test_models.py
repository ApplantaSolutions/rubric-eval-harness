"""Schema-level validation tests for models.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rubric_eval.models import (
    Dimension,
    GateCheckSpec,
    ReliabilityConfig,
    Rule,
    Scale,
    VerdictConfig,
)


class TestScale:
    def test_valid(self):
        s = Scale(min=1, max=5)
        assert s.max - s.min == 4

    def test_min_ge_max_rejected(self):
        with pytest.raises(ValidationError, match="must be less than"):
            Scale(min=5, max=5)

    def test_range_too_small_rejected(self):
        with pytest.raises(ValidationError, match="range too small"):
            Scale(min=1, max=2)

    def test_extra_key_rejected(self):
        with pytest.raises(ValidationError):
            Scale(min=1, max=5, step=1)


class TestRule:
    def test_count_rule_needs_int(self):
        with pytest.raises(ValidationError, match="requires an integer 'value'"):
            Rule(name="w", kind="max_word_count", value="lots")

    def test_count_rule_rejects_negative(self):
        with pytest.raises(ValidationError, match=">= 0"):
            Rule(name="w", kind="max_word_count", value=-3)

    def test_count_rule_rejects_bool(self):
        with pytest.raises(ValidationError, match="not a boolean"):
            Rule(name="w", kind="min_chars", value=True)

    def test_substring_rule_needs_nonempty_string(self):
        with pytest.raises(ValidationError, match="non-empty string"):
            Rule(name="s", kind="required_substring", value="")

    def test_regex_rule_needs_pattern(self):
        with pytest.raises(ValidationError, match="requires 'pattern'"):
            Rule(name="r", kind="forbidden_regex")

    def test_regex_rule_rejects_bad_pattern(self):
        with pytest.raises(ValidationError, match="invalid regex"):
            Rule(name="r", kind="required_regex", pattern="(unclosed")

    def test_valid_json_rule_takes_no_params(self):
        with pytest.raises(ValidationError, match="takes no 'value'"):
            Rule(name="j", kind="valid_json", value=1)

    def test_valid_rules_ok(self):
        Rule(name="a", kind="max_word_count", value=50)
        Rule(name="b", kind="required_substring", value="ticket")
        Rule(name="c", kind="forbidden_regex", pattern=r"\bopinion\b")
        Rule(name="d", kind="valid_json")


class TestGateCheckSpec:
    def test_deterministic_needs_rule(self):
        with pytest.raises(ValidationError, match="requires a 'rule'"):
            GateCheckSpec(text="x", method="deterministic")

    def test_judge_rejects_rule(self):
        with pytest.raises(ValidationError, match="must not include a 'rule'"):
            GateCheckSpec(
                text="x",
                method="judge",
                rule=Rule(name="r", kind="max_chars", value=10),
            )


class TestDimension:
    def test_unknown_type_rejected(self):
        with pytest.raises(ValidationError):
            Dimension(id="d", type="vibes")

    def test_gate_rejects_rules(self):
        with pytest.raises(ValidationError, match="must not define 'rules'"):
            Dimension(
                id="g",
                type="gate",
                rules=[Rule(name="r", kind="max_chars", value=10)],
            )

    def test_deterministic_needs_rules(self):
        with pytest.raises(ValidationError, match="requires at least one rule"):
            Dimension(id="d", type="deterministic")

    def test_judged_needs_anchors(self):
        with pytest.raises(ValidationError, match="requires 'anchors'"):
            Dimension(id="c", type="judged")

    def test_plain_judged_rejects_requires(self):
        with pytest.raises(ValidationError, match="must not set 'requires'"):
            Dimension(
                id="c",
                type="judged",
                requires="reference",
                anchors={1: "a", 5: "b"},
            )

    def test_reference_grounded_defaults_requires(self):
        d = Dimension(id="f", type="reference_grounded", anchors={1: "a", 5: "b"})
        assert d.requires.value == "reference"

    def test_spec_grounded_defaults_requires(self):
        d = Dimension(id="comp", type="spec_grounded", anchors={1: "a", 5: "b"})
        assert d.requires.value == "reference_or_points"


class TestVerdictConfig:
    def test_acceptable_gt_excellent_rejected(self):
        with pytest.raises(ValidationError, match="must be <="):
            VerdictConfig(excellent_min_mean=3.0, acceptable_min_mean=4.0)

    def test_bad_safety_verdict_rejected(self):
        with pytest.raises(ValidationError, match="'needs_work' or 'fail'"):
            VerdictConfig(safety_failure_verdict="explode")


class TestReliabilityConfig:
    def test_defaults_valid(self):
        ReliabilityConfig()

    def test_runs_default_min(self):
        with pytest.raises(ValidationError, match="runs_default must be >= 1"):
            ReliabilityConfig(runs_default=0)

    def test_low_gt_high_stdev_rejected(self):
        with pytest.raises(ValidationError, match="low_variance_stdev must be <="):
            ReliabilityConfig(low_variance_stdev=2.0, high_variance_stdev=1.0)

    def test_fraction_out_of_range_rejected(self):
        with pytest.raises(ValidationError, match="in \\(0.0, 1.0\\]"):
            ReliabilityConfig(stable_agree_fraction=1.5)
