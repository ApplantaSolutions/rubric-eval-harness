"""Judge layer: build prompts, call the provider, parse the structured output.

Two prompt families:
  * judged rubric dimensions  -> a single integer score + rationale + evidence
  * instruction-following      -> per-instruction pass/fail + rationale + evidence

The parser is strict: it never coerces obviously invalid output into a valid
judgment. On malformed output the caller gets one corrective retry; if that also
fails, the run is recorded as a judge error and the pipeline continues.

The judge's returned ``evidence_quote`` is NOT trusted here — the evaluation
pipeline verifies it deterministically against the supplied text (see
``checks.evidence.verify_evidence``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .dataset import EvalItem
from .errors import JudgeParseError, ProviderError
from .models import Dimension, DimensionType, Rubric, Scale
from .providers.base import Provider

_RAW_TRUNCATE = 2000

# --------------------------------------------------------------------------- #
# Parsed judgment structures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DimensionJudgment:
    score: int
    rationale: str
    evidence_quote: str


@dataclass(frozen=True)
class InstructionJudgment:
    index: int
    passed: bool
    rationale: str
    evidence_quote: str


# --------------------------------------------------------------------------- #
# JSON extraction + parsing
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _first_json_object(text: str) -> str:
    """Return the first balanced ``{...}`` block, honouring string literals."""
    start = text.find("{")
    if start == -1:
        raise JudgeParseError("no JSON object found in judge output")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise JudgeParseError("unbalanced JSON object in judge output")


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from judge output. Tolerates ```json fences and a
    limited amount of surrounding prose; rejects anything else."""
    stripped = text.strip()
    for candidate in _json_candidates(stripped):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        raise JudgeParseError(f"expected a JSON object, got {type(parsed).__name__}")
    raise JudgeParseError("could not parse a JSON object from judge output")


def _json_candidates(text: str):
    yield text
    fence = _FENCE_RE.search(text)
    if fence:
        yield fence.group(1)
    try:
        yield _first_json_object(text)
    except JudgeParseError:
        pass


def _require_str(obj: dict[str, Any], key: str) -> str:
    if key not in obj:
        raise JudgeParseError(f"missing required field '{key}'")
    value = obj[key]
    if not isinstance(value, str):
        raise JudgeParseError(f"field '{key}' must be a string, got {type(value).__name__}")
    return value


def _coerce_score(value: Any, scale: Scale) -> int:
    if isinstance(value, bool):
        raise JudgeParseError("field 'score' must be a number, got boolean")
    if isinstance(value, int):
        score = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise JudgeParseError(f"field 'score' must be an integer, got {value}")
        score = int(value)
    else:
        raise JudgeParseError(f"field 'score' must be a number, got {type(value).__name__}")
    if score < scale.min or score > scale.max:
        raise JudgeParseError(
            f"score {score} is outside the rubric scale [{scale.min}, {scale.max}]"
        )
    return score


def parse_dimension_judgment(text: str, scale: Scale) -> DimensionJudgment:
    obj = extract_json_object(text)
    if "score" not in obj:
        raise JudgeParseError("missing required field 'score'")
    score = _coerce_score(obj["score"], scale)
    rationale = _require_str(obj, "rationale").strip()
    if not rationale:
        raise JudgeParseError("field 'rationale' must not be empty")
    evidence = obj.get("evidence_quote", "")
    if not isinstance(evidence, str):
        raise JudgeParseError(
            f"field 'evidence_quote' must be a string, got {type(evidence).__name__}"
        )
    return DimensionJudgment(score=score, rationale=rationale, evidence_quote=evidence)


def parse_instruction_judgments(text: str, expected: int) -> list[InstructionJudgment]:
    obj = extract_json_object(text)
    if "results" not in obj or not isinstance(obj["results"], list):
        raise JudgeParseError("missing required field 'results' (a list)")
    rows = obj["results"]
    if len(rows) != expected:
        raise JudgeParseError(f"expected {expected} instruction result(s), got {len(rows)}")
    out: list[InstructionJudgment] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise JudgeParseError("each 'results' entry must be an object")
        idx = row.get("index")
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise JudgeParseError("instruction result 'index' must be an integer")
        if idx < 0 or idx >= expected:
            raise JudgeParseError(f"instruction result 'index' {idx} out of range")
        if idx in seen:
            raise JudgeParseError(f"duplicate instruction result 'index' {idx}")
        seen.add(idx)
        status = _require_str(row, "status").strip().lower()
        if status not in ("pass", "fail"):
            raise JudgeParseError(
                f"instruction result 'status' must be 'pass' or 'fail', got {status!r}"
            )
        rationale = _require_str(row, "rationale").strip()
        evidence = row.get("evidence_quote", "")
        if not isinstance(evidence, str):
            raise JudgeParseError("instruction result 'evidence_quote' must be a string")
        out.append(
            InstructionJudgment(
                index=idx,
                passed=(status == "pass"),
                rationale=rationale,
                evidence_quote=evidence,
            )
        )
    out.sort(key=lambda j: j.index)
    return out


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #

_DIMENSION_SYSTEM = (
    "You are a careful evaluation judge. You score ONE specific quality dimension "
    "of a response against an explicit rubric. Follow the rubric anchors exactly. "
    "Output ONLY a single JSON object and nothing else."
)

_REFERENCE_RULES = (
    "Judge this dimension ONLY against the SUPPLIED REFERENCE below. Do not use "
    "outside knowledge. If the reference does not support a claim in the response, "
    "treat that claim as unsupported. In 'evidence_quote', return a span copied "
    "VERBATIM from the reference that best supports or contradicts your score — do "
    "not paraphrase and do not invent a quotation. If no relevant span exists, use "
    'an empty string ("").'
)

_INSTRUCTION_SYSTEM = (
    "You check whether a response follows explicit instructions. For each "
    "instruction, decide pass or fail based ONLY on the response. 'fail' means the "
    "response clearly does not satisfy the instruction. Output ONLY a single JSON "
    "object and nothing else."
)


def _anchor_lines(dim: Dimension) -> str:
    return "\n".join(
        f"  {score} = {text}" for score, text in sorted(dim.anchors.items(), reverse=True)
    )


def build_dimension_prompt(rubric: Rubric, dim: Dimension, item: EvalItem) -> tuple[str, str]:
    is_reference_grounded = dim.type is DimensionType.REFERENCE_GROUNDED
    use_reference = item.has_reference() and dim.type in (
        DimensionType.REFERENCE_GROUNDED,
        DimensionType.SPEC_GROUNDED,
    )

    system = _DIMENSION_SYSTEM
    if is_reference_grounded:
        system = f"{system}\n\n{_REFERENCE_RULES}"

    parts = [
        "TASK GIVEN TO THE MODEL:",
        item.task,
        "",
        "CANDIDATE RESPONSE TO EVALUATE:",
        item.candidate_response,
        "",
        f"DIMENSION TO SCORE: {dim.id}",
    ]
    if dim.description:
        parts.append(dim.description)
    parts += [
        "",
        f"SCORING ANCHORS (score is an integer from {rubric.scale.min} to {rubric.scale.max}):",
        _anchor_lines(dim),
    ]
    if use_reference:
        parts += ["", "SUPPLIED REFERENCE (judge only against this):", item.reference or ""]
    if dim.type is DimensionType.SPEC_GROUNDED and item.has_required_points():
        parts += [
            "",
            "REQUIRED POINTS the response should cover:",
            *(f"  - {p}" for p in item.required_points),
        ]

    evidence_hint = (
        "a span copied verbatim from the reference, or an empty string"
        if is_reference_grounded
        else "an empty string, or a short verbatim span if genuinely useful"
    )
    parts += [
        "",
        "Return ONLY this JSON object:",
        json.dumps(
            {
                "score": f"<integer {rubric.scale.min}-{rubric.scale.max}>",
                "rationale": "<2-4 sentences tied to the anchors>",
                "evidence_quote": f"<{evidence_hint}>",
            },
            indent=2,
        ),
    ]
    return system, "\n".join(parts)


def build_instruction_prompt(item: EvalItem, instruction_texts: list[str]) -> tuple[str, str]:
    numbered = "\n".join(f"  {i}. {t}" for i, t in enumerate(instruction_texts))
    parts = [
        "TASK GIVEN TO THE MODEL:",
        item.task,
        "",
        "CANDIDATE RESPONSE:",
        item.candidate_response,
        "",
        "INSTRUCTIONS TO CHECK:",
        numbered,
        "",
        "For each instruction, decide pass or fail. If genuinely ambiguous, take "
        "the reading a careful reviewer would take and explain briefly.",
        "",
        "Return ONLY this JSON object:",
        json.dumps(
            {
                "results": [
                    {
                        "index": 0,
                        "status": "pass | fail",
                        "rationale": "<1-2 sentences>",
                        "evidence_quote": "<optional verbatim span from the response>",
                    }
                ]
            },
            indent=2,
        ),
    ]
    return _INSTRUCTION_SYSTEM, "\n".join(parts)


# --------------------------------------------------------------------------- #
# Call + one corrective retry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class JudgeCallResult:
    parsed: Any | None
    raw: str
    error: str | None
    attempts: int


def _repair_prompt(user: str, error: str) -> str:
    return (
        f"{user}\n\n"
        f"YOUR PREVIOUS RESPONSE COULD NOT BE PARSED: {error}\n"
        "Return ONLY a single valid JSON object with exactly the fields shown "
        "above. No prose, no markdown fences, no extra fields."
    )


def call_judge(
    provider: Provider,
    *,
    system: str,
    user: str,
    parse: Callable[[str], Any],
    temperature: float,
    metadata: dict | None = None,
    max_tokens: int = 1024,
) -> JudgeCallResult:
    """Call the provider, parse, and retry once with a corrective prompt on a
    parse failure. A ProviderError is NOT retried — it propagates to the caller.
    """
    meta = dict(metadata or {})

    meta["attempt"] = 1
    raw = provider.complete(
        system=system, user=user, temperature=temperature, max_tokens=max_tokens, metadata=meta
    )
    try:
        return JudgeCallResult(parsed=parse(raw), raw=_truncate(raw), error=None, attempts=1)
    except JudgeParseError as first_err:
        first_message = str(first_err)

    meta["attempt"] = 2
    raw2 = provider.complete(
        system=system,
        user=_repair_prompt(user, first_message),
        temperature=temperature,
        max_tokens=max_tokens,
        metadata=meta,
    )
    try:
        return JudgeCallResult(parsed=parse(raw2), raw=_truncate(raw2), error=None, attempts=2)
    except JudgeParseError as second_err:
        return JudgeCallResult(
            parsed=None,
            raw=_truncate(raw2),
            error=f"malformed judge output after retry: {second_err}",
            attempts=2,
        )


def _truncate(text: str) -> str:
    if len(text) <= _RAW_TRUNCATE:
        return text
    return text[:_RAW_TRUNCATE] + f"... [truncated {len(text) - _RAW_TRUNCATE} chars]"


__all__ = [
    "DimensionJudgment",
    "InstructionJudgment",
    "JudgeCallResult",
    "ProviderError",
    "build_dimension_prompt",
    "build_instruction_prompt",
    "call_judge",
    "extract_json_object",
    "parse_dimension_judgment",
    "parse_instruction_judgments",
]
