"""Rubric configuration schemas.

These models describe a *rubric* (how to evaluate) and are loaded from YAML.
They validate strictly: unknown keys and contradictory configuration are
rejected with a message that names the offending field. Nothing is silently
repaired.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class DimensionType(StrEnum):
    """What kind of evaluation a dimension performs."""

    GATE = "gate"  # instruction-following checklist; PASS/FAIL gate
    DETERMINISTIC = "deterministic"  # code rules only, no model
    REFERENCE_GROUNDED = "reference_grounded"  # judged; needs a reference passage
    SPEC_GROUNDED = "spec_grounded"  # judged; needs required_points or a reference
    JUDGED = "judged"  # judged; no evidence requirement (e.g. clarity)


JUDGED_TYPES: frozenset[DimensionType] = frozenset(
    {DimensionType.REFERENCE_GROUNDED, DimensionType.SPEC_GROUNDED, DimensionType.JUDGED}
)


class RuleKind(StrEnum):
    """Deterministic checks that require no model."""

    MAX_WORD_COUNT = "max_word_count"
    MIN_WORD_COUNT = "min_word_count"
    MAX_SENTENCES = "max_sentences"
    MIN_SENTENCES = "min_sentences"
    MAX_CHARS = "max_chars"
    MIN_CHARS = "min_chars"
    REQUIRED_SUBSTRING = "required_substring"
    FORBIDDEN_SUBSTRING = "forbidden_substring"
    REQUIRED_REGEX = "required_regex"
    FORBIDDEN_REGEX = "forbidden_regex"
    VALID_JSON = "valid_json"


_COUNT_KINDS = frozenset(
    {
        RuleKind.MAX_WORD_COUNT,
        RuleKind.MIN_WORD_COUNT,
        RuleKind.MAX_SENTENCES,
        RuleKind.MIN_SENTENCES,
        RuleKind.MAX_CHARS,
        RuleKind.MIN_CHARS,
    }
)
_SUBSTRING_KINDS = frozenset({RuleKind.REQUIRED_SUBSTRING, RuleKind.FORBIDDEN_SUBSTRING})
_REGEX_KINDS = frozenset({RuleKind.REQUIRED_REGEX, RuleKind.FORBIDDEN_REGEX})


class EvidenceRequirement(StrEnum):
    """What a judged dimension needs before it can be scored at all."""

    NONE = "none"
    REFERENCE = "reference"
    REQUIRED_POINTS = "required_points"
    REFERENCE_OR_POINTS = "reference_or_points"


class InstructionCheckMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    JUDGE = "judge"


# --------------------------------------------------------------------------- #
# Rubric building blocks
# --------------------------------------------------------------------------- #


class Scale(BaseModel):
    """Integer scoring scale shared by every judged dimension in a rubric."""

    model_config = ConfigDict(extra="forbid")

    min: int
    max: int

    @model_validator(mode="after")
    def _check(self) -> Scale:
        if self.min >= self.max:
            raise ValueError(f"scale.min ({self.min}) must be less than scale.max ({self.max})")
        if self.max - self.min < 2:
            raise ValueError(
                f"scale range too small: max - min must be >= 2 (got {self.max - self.min})"
            )
        return self


class Rule(BaseModel):
    """A single deterministic check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: RuleKind
    value: int | str | None = None
    pattern: str | None = None
    case_sensitive: bool = True

    @field_validator("value", mode="before")
    @classmethod
    def _reject_bool_value(cls, v: object) -> object:
        if isinstance(v, bool):
            raise ValueError("'value' must be an integer or a string, not a boolean")
        return v

    @model_validator(mode="after")
    def _check(self) -> Rule:
        if self.kind in _COUNT_KINDS:
            if not isinstance(self.value, int) or isinstance(self.value, bool):
                raise ValueError(
                    f"rule '{self.name}': kind '{self.kind.value}' requires an integer 'value'"
                )
            if self.value < 0:
                raise ValueError(f"rule '{self.name}': 'value' must be >= 0 (got {self.value})")
            if self.pattern is not None:
                raise ValueError(
                    f"rule '{self.name}': kind '{self.kind.value}' does not take 'pattern'"
                )
        elif self.kind in _SUBSTRING_KINDS:
            if not isinstance(self.value, str) or self.value == "":
                raise ValueError(
                    f"rule '{self.name}': kind '{self.kind.value}' requires a non-empty string 'value'"
                )
        elif self.kind in _REGEX_KINDS:
            if not self.pattern:
                raise ValueError(f"rule '{self.name}': kind '{self.kind.value}' requires 'pattern'")
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"rule '{self.name}': invalid regex pattern: {exc}") from exc
            if self.value is not None:
                raise ValueError(
                    f"rule '{self.name}': kind '{self.kind.value}' does not take 'value'"
                )
        elif self.kind is RuleKind.VALID_JSON:
            if self.value is not None or self.pattern is not None:
                raise ValueError(
                    f"rule '{self.name}': kind 'valid_json' takes no 'value' or 'pattern'"
                )
        return self


class GateCheckSpec(BaseModel):
    """A rubric-level instruction that applies to every item (in addition to
    the per-item ``instructions`` list)."""

    model_config = ConfigDict(extra="forbid")

    text: str
    method: InstructionCheckMethod = InstructionCheckMethod.JUDGE
    rule: Rule | None = None

    @model_validator(mode="after")
    def _check(self) -> GateCheckSpec:
        if self.method is InstructionCheckMethod.DETERMINISTIC and self.rule is None:
            raise ValueError(f"gate check '{self.text}': method 'deterministic' requires a 'rule'")
        if self.method is InstructionCheckMethod.JUDGE and self.rule is not None:
            raise ValueError(f"gate check '{self.text}': method 'judge' must not include a 'rule'")
        return self


class Dimension(BaseModel):
    """One dimension of a rubric."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: DimensionType
    description: str = ""

    # gate
    global_checks: list[GateCheckSpec] = Field(default_factory=list)
    include_item_instructions: bool = True

    # deterministic
    rules: list[Rule] = Field(default_factory=list)

    # judged
    requires: EvidenceRequirement = EvidenceRequirement.NONE
    anchors: dict[int, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Dimension:
        if self.type is DimensionType.GATE:
            if self.rules:
                raise ValueError(
                    f"dimension '{self.id}': a 'gate' dimension must not define 'rules'"
                )
            if self.anchors:
                raise ValueError(
                    f"dimension '{self.id}': a 'gate' dimension must not define 'anchors'"
                )
            if self.requires is not EvidenceRequirement.NONE:
                raise ValueError(
                    f"dimension '{self.id}': a 'gate' dimension must not set 'requires'"
                )
        elif self.type is DimensionType.DETERMINISTIC:
            if not self.rules:
                raise ValueError(
                    f"dimension '{self.id}': a 'deterministic' dimension requires at least one rule"
                )
            if self.anchors or self.global_checks:
                raise ValueError(
                    f"dimension '{self.id}': a 'deterministic' dimension must not define "
                    f"'anchors' or 'global_checks'"
                )
            if self.requires is not EvidenceRequirement.NONE:
                raise ValueError(
                    f"dimension '{self.id}': a 'deterministic' dimension must not set 'requires'"
                )
        elif self.type in JUDGED_TYPES:
            if not self.anchors:
                raise ValueError(
                    f"dimension '{self.id}': a '{self.type.value}' dimension requires 'anchors'"
                )
            if self.rules or self.global_checks:
                raise ValueError(
                    f"dimension '{self.id}': a judged dimension must not define 'rules' or 'global_checks'"
                )
            if self.type is DimensionType.REFERENCE_GROUNDED:
                if self.requires is EvidenceRequirement.NONE:
                    self.requires = EvidenceRequirement.REFERENCE
                if self.requires not in (
                    EvidenceRequirement.REFERENCE,
                    EvidenceRequirement.REFERENCE_OR_POINTS,
                ):
                    raise ValueError(
                        f"dimension '{self.id}': 'reference_grounded' requires evidence from a reference "
                        f"(requires must be 'reference' or 'reference_or_points')"
                    )
            elif self.type is DimensionType.SPEC_GROUNDED:
                if self.requires is EvidenceRequirement.NONE:
                    self.requires = EvidenceRequirement.REFERENCE_OR_POINTS
            elif (
                self.type is DimensionType.JUDGED and self.requires is not EvidenceRequirement.NONE
            ):
                raise ValueError(
                    f"dimension '{self.id}': a plain 'judged' dimension must not set 'requires' "
                    f"(it has no reference to ground against)"
                )
        return self


class VerdictConfig(BaseModel):
    """Thresholds and gates that turn dimension results into a verdict."""

    model_config = ConfigDict(extra="forbid")

    excellent_min_mean: float = 4.0
    acceptable_min_mean: float = 3.0
    needs_work_floor_any: float = 2.5
    safety_dimension_ids: list[str] = Field(default_factory=list)
    safety_failure_verdict: str = "needs_work"  # "needs_work" | "fail"

    @model_validator(mode="after")
    def _check(self) -> VerdictConfig:
        if self.acceptable_min_mean > self.excellent_min_mean:
            raise ValueError("verdict.acceptable_min_mean must be <= verdict.excellent_min_mean")
        if self.safety_failure_verdict not in ("needs_work", "fail"):
            raise ValueError(
                "verdict.safety_failure_verdict must be 'needs_work' or 'fail' "
                f"(got '{self.safety_failure_verdict}')"
            )
        return self


class ReliabilityConfig(BaseModel):
    """Configurable *operational heuristics* for flagging unstable judge
    behaviour. These are NOT statistically validated boundaries — see
    docs/methodology.md. Raw per-run numbers are always reported alongside
    any label derived from these values.
    """

    model_config = ConfigDict(extra="forbid")

    runs_default: int = 5
    disagreement_threshold: int = 2
    unreliable_disagreement_rate: float = 0.34
    low_variance_stdev: float = 0.5
    high_variance_stdev: float = 1.0
    stable_agree_fraction: float = 0.8

    @model_validator(mode="after")
    def _check(self) -> ReliabilityConfig:
        if self.runs_default < 1:
            raise ValueError("reliability.runs_default must be >= 1")
        if self.disagreement_threshold < 1:
            raise ValueError("reliability.disagreement_threshold must be >= 1")
        if self.low_variance_stdev < 0 or self.high_variance_stdev < 0:
            raise ValueError("reliability stdev thresholds must be >= 0")
        if self.low_variance_stdev > self.high_variance_stdev:
            raise ValueError(
                "reliability.low_variance_stdev must be <= reliability.high_variance_stdev"
            )
        for name in ("unreliable_disagreement_rate", "stable_agree_fraction"):
            v = getattr(self, name)
            if not 0.0 < v <= 1.0:
                raise ValueError(f"reliability.{name} must be in (0.0, 1.0]")
        return self


class Rubric(BaseModel):
    """A complete rubric."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    version: int = 1
    description: str = ""
    scale: Scale
    dimensions: list[Dimension]
    verdict: VerdictConfig = Field(default_factory=VerdictConfig)
    reliability: ReliabilityConfig = Field(default_factory=ReliabilityConfig)

    @model_validator(mode="after")
    def _check(self) -> Rubric:
        if not self.dimensions:
            raise ValueError("rubric: at least one dimension is required")

        seen: set[str] = set()
        for dim in self.dimensions:
            if dim.id in seen:
                raise ValueError(f"rubric: duplicate dimension id '{dim.id}'")
            seen.add(dim.id)

        gates = [d for d in self.dimensions if d.type is DimensionType.GATE]
        if len(gates) > 1:
            raise ValueError("rubric: at most one 'gate' dimension is allowed")

        for dim in self.dimensions:
            if not dim.anchors:
                continue
            for key in dim.anchors:
                if key < self.scale.min or key > self.scale.max:
                    raise ValueError(
                        f"dimension '{dim.id}': anchor key {key} is outside the scale "
                        f"[{self.scale.min}, {self.scale.max}]"
                    )
            if self.scale.min not in dim.anchors or self.scale.max not in dim.anchors:
                raise ValueError(
                    f"dimension '{dim.id}': anchors must include both scale endpoints "
                    f"({self.scale.min} and {self.scale.max})"
                )

        det_ids = {d.id for d in self.dimensions if d.type is DimensionType.DETERMINISTIC}
        for sid in self.verdict.safety_dimension_ids:
            if sid not in det_ids:
                raise ValueError(
                    f"verdict.safety_dimension_ids: '{sid}' is not a 'deterministic' dimension "
                    f"in this rubric"
                )
        return self

    # -- convenience accessors ------------------------------------------- #

    def gate_dimension(self) -> Dimension | None:
        for dim in self.dimensions:
            if dim.type is DimensionType.GATE:
                return dim
        return None

    def deterministic_dimensions(self) -> list[Dimension]:
        return [d for d in self.dimensions if d.type is DimensionType.DETERMINISTIC]

    def judged_dimensions(self) -> list[Dimension]:
        return [d for d in self.dimensions if d.type in JUDGED_TYPES]
