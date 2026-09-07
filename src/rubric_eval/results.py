"""Result schemas: the data structures produced by an evaluation run.

Kept separate from ``models.py`` (rubric configuration) so the two concerns
stay small and independently testable. These structures are the single source
of truth for both the JSON report and the HTML report.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .models import DimensionType, InstructionCheckMethod

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class CheckOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class InstructionStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    PENDING_JUDGE = "pending_judge"  # deterministic layer cannot decide; judge must
    ERROR = "error"


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"  # at least one instruction still needs the judge; none failed
    ERROR = "error"  # a judged instruction could not be evaluated (judge/provider error)


class DimensionStatus(StrEnum):
    EVALUATED = "evaluated"
    NOT_EVALUATED = "not_evaluated"  # required evidence absent — deliberately NOT scored
    PENDING_JUDGE = "pending_judge"  # judged dimension awaiting the judge layer


class ReliabilityLabel(StrEnum):
    STABLE = "stable"
    SOME_VARIANCE = "some_variance"
    UNRELIABLE = "unreliable"
    NOT_APPLICABLE = "not_applicable"  # single run, or not a judged dimension


class Verdict(StrEnum):
    FAIL = "Fail"
    NEEDS_WORK = "Needs work"
    ACCEPTABLE = "Acceptable"
    EXCELLENT = "Excellent"
    UNRESOLVED = "Unresolved"  # judged dimensions / gate not yet evaluated


VERDICT_ORDER: dict[Verdict, int] = {
    Verdict.FAIL: 0,
    Verdict.NEEDS_WORK: 1,
    Verdict.ACCEPTABLE: 2,
    Verdict.EXCELLENT: 3,
}


# --------------------------------------------------------------------------- #
# Leaf results
# --------------------------------------------------------------------------- #


class CheckResult(BaseModel):
    """Outcome of one deterministic rule."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    expected: str
    observed: str
    outcome: CheckOutcome
    explanation: str


class EvidenceCheck(BaseModel):
    """Deterministic verification of a quotation the judge claims supports its
    score. The judge itself can hallucinate evidence, so this is never trusted
    blindly — the quote must actually occur in the supplied reference text.
    """

    model_config = ConfigDict(extra="forbid")

    quote: str
    verified: bool
    method: str  # exact | normalized | not_found | no_reference | empty
    note: str = ""


class InstructionResult(BaseModel):
    """Outcome of one explicit instruction in the instruction-following gate."""

    model_config = ConfigDict(extra="forbid")

    text: str
    method: InstructionCheckMethod
    status: InstructionStatus
    detail: str = ""
    check: CheckResult | None = None  # populated when method == deterministic
    evidence: EvidenceCheck | None = None  # populated by the judge layer, if cited


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_id: str
    instructions: list[InstructionResult]
    status: GateStatus


class JudgeRunResult(BaseModel):
    """One run of the judge for one judged dimension. Filled by the judge
    layer (Checkpoint 3); defined here so the schema is stable."""

    model_config = ConfigDict(extra="forbid")

    run_index: int
    score: int | None = None
    rationale: str = ""
    evidence: EvidenceCheck | None = None
    attempts: int = 1  # 2 means the first response was malformed and a retry succeeded
    raw_response: str | None = None
    error: str | None = None


class DimensionResult(BaseModel):
    """Aggregated result for one rubric dimension on one item."""

    model_config = ConfigDict(extra="forbid")

    dimension_id: str
    type: DimensionType
    status: DimensionStatus
    not_evaluated_reason: str | None = None

    # deterministic dimensions
    checks: list[CheckResult] = Field(default_factory=list)
    deterministic_passed: bool | None = None

    # gate dimension
    gate: GateResult | None = None

    # judged dimensions (filled in Checkpoint 3)
    runs: list[JudgeRunResult] = Field(default_factory=list)
    scores: list[int] = Field(default_factory=list)
    mean: float | None = None
    stdev: float | None = None
    minimum: int | None = None
    maximum: int | None = None
    pairwise_disagreement_rate: float | None = None
    reliability_label: ReliabilityLabel | None = None
    judge_error_count: int = 0
    evidence_all_verified: bool | None = None
    evidence_any_unverified: bool | None = None


class VerdictExplanation(BaseModel):
    """The verdict plus every input that produced it — so it can be audited."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    gate_status: GateStatus
    deterministic_all_passed: bool
    judged_mean: float | None = None
    evaluated_judged_dimensions: list[str] = Field(default_factory=list)
    not_evaluated_dimensions: list[str] = Field(default_factory=list)
    unresolved_dimensions: list[str] = Field(default_factory=list)
    capped_by: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class VerdictStabilityResult(BaseModel):
    """How stable the item verdict is across the N judged runs.

    Instruction judging happens once (not per run); per-run verdict variation
    therefore comes only from the judged-dimension scores. A run in which any
    evaluable judged dimension hit a judge error is recorded as 'Unresolved'
    for that run. Ties for the modal verdict resolve to the more conservative
    (lower) verdict. See docs/methodology.md and tests/test_verdict_stability.py.
    """

    model_config = ConfigDict(extra="forbid")

    per_run_verdicts: list[str]
    modal_verdict: str
    distribution: dict[str, int]
    agreement_fraction: float
    note: str = ""


class ItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    task: str
    candidate_response: str
    scenario: str | None = None
    author_note: str | None = None
    dimensions: list[DimensionResult]
    verdict: VerdictExplanation
    verdict_stability: VerdictStabilityResult | None = None
    indicative_score: float | None = None
    errors: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Run-level structures (assembled by the report layer)
# --------------------------------------------------------------------------- #


class RunMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harness_version: str
    generated_at: str
    rubric_id: str
    rubric_title: str
    rubric_version: int
    dataset_path: str
    dataset_item_count: int
    provider: str
    judge_model: str | None = None
    judge_temperature: float | None = None
    runs: int
    command: str | None = None
    git_commit: str | None = None


class ReportSummary(BaseModel):
    """Aggregate view. Unresolved verdicts, gate errors, NOT_EVALUATED
    dimensions, unverified evidence, and judge errors are all counted
    explicitly — never folded away."""

    model_config = ConfigDict(extra="forbid")

    item_count: int
    verdict_counts: dict[str, int]  # every Verdict, incl. "Unresolved"
    gate_status_counts: dict[str, int]  # pass / fail / pending / error
    instruction_check_counts: dict[str, int]  # pass / fail / pending_judge / error
    reliability_counts: dict[str, int]  # stable / some_variance / unreliable / not_applicable
    evaluated_judged_dimension_count: int
    not_evaluated_dimension_count: int
    unverified_evidence_dimension_count: int
    judge_error_run_count: int
    items_with_errors_count: int
    dataset_verdict_agreement: float | None  # mean of per-item stability agreement


class RunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: RunMeta
    items: list[ItemResult]
    summary: ReportSummary
