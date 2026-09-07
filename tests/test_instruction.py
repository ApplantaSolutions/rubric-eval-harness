"""Instruction-following gate (deterministic layer)."""

from __future__ import annotations

from rubric_eval.checks.instruction import evaluate_gate, gate_status
from rubric_eval.dataset import EvalItem
from rubric_eval.models import Dimension, GateCheckSpec, Rule
from rubric_eval.results import GateStatus, InstructionResult, InstructionStatus


def _item(response: str, instructions: list[str] | None = None) -> EvalItem:
    return EvalItem(
        id="i",
        task="t",
        candidate_response=response,
        instructions=instructions or [],
    )


def _gate(**kw) -> Dimension:
    base = {"id": "g", "type": "gate"}
    base.update(kw)
    return Dimension(**base)


def test_deterministic_check_pass():
    dim = _gate(
        global_checks=[
            GateCheckSpec(
                text="<= 5 words",
                method="deterministic",
                rule=Rule(name="w", kind="max_word_count", value=5),
            )
        ],
        include_item_instructions=False,
    )
    result = evaluate_gate(dim, _item("one two three"))
    assert result.status is GateStatus.PASS
    assert result.instructions[0].status is InstructionStatus.PASS
    assert result.instructions[0].check is not None


def test_deterministic_check_fail_fails_gate_even_with_pendings():
    dim = _gate(
        global_checks=[
            GateCheckSpec(
                text="<= 2 words",
                method="deterministic",
                rule=Rule(name="w", kind="max_word_count", value=2),
            ),
            GateCheckSpec(text="neutral tone", method="judge"),
        ],
        include_item_instructions=False,
    )
    result = evaluate_gate(dim, _item("one two three four"))
    assert result.status is GateStatus.FAIL


def test_judge_check_is_pending_not_fabricated():
    dim = _gate(
        global_checks=[GateCheckSpec(text="no opinion", method="judge")],
        include_item_instructions=False,
    )
    result = evaluate_gate(dim, _item("this is clearly the best option"))
    assert result.status is GateStatus.PENDING
    inst = result.instructions[0]
    assert inst.status is InstructionStatus.PENDING_JUDGE
    assert inst.check is None
    assert "judge" in inst.detail.lower()


def test_item_instructions_are_pending():
    dim = _gate(include_item_instructions=True)
    result = evaluate_gate(dim, _item("x", instructions=["be brief", "be kind"]))
    assert len(result.instructions) == 2
    assert all(i.status is InstructionStatus.PENDING_JUDGE for i in result.instructions)
    assert result.status is GateStatus.PENDING


def test_include_item_instructions_false_ignores_them():
    dim = _gate(
        global_checks=[
            GateCheckSpec(
                text="<= 10 words",
                method="deterministic",
                rule=Rule(name="w", kind="max_word_count", value=10),
            )
        ],
        include_item_instructions=False,
    )
    result = evaluate_gate(dim, _item("short", instructions=["ignored instruction"]))
    assert len(result.instructions) == 1
    assert result.status is GateStatus.PASS


def test_all_deterministic_pass_gives_pass():
    dim = _gate(
        global_checks=[
            GateCheckSpec(
                text="<= 10 words",
                method="deterministic",
                rule=Rule(name="w", kind="max_word_count", value=10),
            ),
            GateCheckSpec(
                text="no headers",
                method="deterministic",
                rule=Rule(name="h", kind="forbidden_regex", pattern=r"(?m)^\s*#"),
            ),
        ],
        include_item_instructions=False,
    )
    assert evaluate_gate(dim, _item("a clean short line")).status is GateStatus.PASS


def test_gate_status_helper():
    def ir(status):
        return InstructionResult(text="x", method="judge", status=status)

    assert gate_status([ir(InstructionStatus.PASS)]) is GateStatus.PASS
    assert (
        gate_status([ir(InstructionStatus.PASS), ir(InstructionStatus.PENDING_JUDGE)])
        is GateStatus.PENDING
    )
    assert (
        gate_status([ir(InstructionStatus.FAIL), ir(InstructionStatus.PENDING_JUDGE)])
        is GateStatus.FAIL
    )
