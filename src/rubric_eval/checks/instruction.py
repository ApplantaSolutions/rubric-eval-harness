"""Instruction-following gate.

Every explicit instruction is checked. An instruction is resolved
deterministically when the rubric attaches a rule to it; otherwise it is
marked PENDING_JUDGE and left for the judge layer (Checkpoint 3) to resolve.
The deterministic layer never fabricates a judgment.

Gate status:
  * FAIL     — at least one instruction failed (deterministic evidence).
  * PENDING  — no failures, but at least one instruction still needs the judge.
  * PASS     — every instruction passed and none needed the judge.
"""

from __future__ import annotations

from ..dataset import EvalItem
from ..models import Dimension, InstructionCheckMethod
from ..results import (
    CheckOutcome,
    GateResult,
    GateStatus,
    InstructionResult,
    InstructionStatus,
)
from .deterministic import apply_rule

_PENDING_DETAIL = "Requires judge evaluation; not decided by the deterministic layer."


def evaluate_gate(dim: Dimension, item: EvalItem) -> GateResult:
    instructions: list[InstructionResult] = []

    for spec in dim.global_checks:
        if spec.method is InstructionCheckMethod.DETERMINISTIC:
            assert spec.rule is not None  # guaranteed by GateCheckSpec validation
            check = apply_rule(spec.rule, item.candidate_response)
            status = (
                InstructionStatus.PASS
                if check.outcome is CheckOutcome.PASS
                else InstructionStatus.FAIL
            )
            instructions.append(
                InstructionResult(
                    text=spec.text,
                    method=InstructionCheckMethod.DETERMINISTIC,
                    status=status,
                    detail=check.explanation,
                    check=check,
                )
            )
        else:
            instructions.append(
                InstructionResult(
                    text=spec.text,
                    method=InstructionCheckMethod.JUDGE,
                    status=InstructionStatus.PENDING_JUDGE,
                    detail=_PENDING_DETAIL,
                )
            )

    if dim.include_item_instructions:
        for text in item.instructions:
            instructions.append(
                InstructionResult(
                    text=text,
                    method=InstructionCheckMethod.JUDGE,
                    status=InstructionStatus.PENDING_JUDGE,
                    detail=_PENDING_DETAIL,
                )
            )

    return GateResult(
        dimension_id=dim.id,
        instructions=instructions,
        status=gate_status(instructions),
    )


def gate_status(instructions: list[InstructionResult]) -> GateStatus:
    # A proven deterministic failure is never rescued by anything else.
    if any(i.status is InstructionStatus.FAIL for i in instructions):
        return GateStatus.FAIL
    if any(i.status is InstructionStatus.ERROR for i in instructions):
        return GateStatus.ERROR
    if any(i.status is InstructionStatus.PENDING_JUDGE for i in instructions):
        return GateStatus.PENDING
    return GateStatus.PASS
