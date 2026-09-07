"""Evidence handling for reference-grounded dimensions.

Two responsibilities:

1. ``resolve_evidence_requirement`` — decide whether a judged dimension *can*
   be scored at all. If the rubric says a dimension needs a reference (or
   required_points) and the item supplies neither, the dimension is
   NOT_EVALUATED. It is never scored zero.

2. ``verify_evidence`` — when the judge returns a quotation it claims supports
   its score, check that the quotation actually occurs in the supplied
   reference. The judge can hallucinate evidence, so a returned quote is only
   "verified" if the deterministic layer can find it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..dataset import EvalItem
from ..models import Dimension, EvidenceRequirement
from ..results import EvidenceCheck

_WS_RE = re.compile(r"\s+")
_QUOTE_MAP = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "…": "...",
}


def _normalize(text: str) -> str:
    for src, dst in _QUOTE_MAP.items():
        text = text.replace(src, dst)
    text = text.strip()
    for lead in ('"', "'", "...", "…"):
        if text.startswith(lead):
            text = text[len(lead) :]
    for trail in ('"', "'", "...", "…"):
        if text.endswith(trail):
            text = text[: -len(trail)]
    text = _WS_RE.sub(" ", text).strip()
    return text.lower()


def verify_evidence(quote: str | None, reference: str | None) -> EvidenceCheck:
    raw = (quote or "").strip()
    if not raw:
        return EvidenceCheck(
            quote="",
            verified=False,
            method="empty",
            note="The judge returned no supporting quotation.",
        )
    if reference is None:
        return EvidenceCheck(
            quote=raw,
            verified=False,
            method="no_reference",
            note=(
                "The judge returned a quotation but this item has no reference text "
                "to verify it against."
            ),
        )

    if raw in reference:
        return EvidenceCheck(quote=raw, verified=True, method="exact")

    norm_quote = _normalize(raw)
    if norm_quote and norm_quote in _normalize(reference):
        return EvidenceCheck(
            quote=raw,
            verified=True,
            method="normalized",
            note=(
                "Matched the reference after normalizing whitespace, quote characters, "
                "and surrounding punctuation."
            ),
        )

    return EvidenceCheck(
        quote=raw,
        verified=False,
        method="not_found",
        note=(
            "The quoted span does not occur in the supplied reference. Treat it as "
            "unverified and possibly fabricated by the judge model."
        ),
    )


@dataclass(frozen=True)
class EvidenceAvailability:
    can_evaluate: bool
    reason: str | None = None


def resolve_evidence_requirement(dim: Dimension, item: EvalItem) -> EvidenceAvailability:
    req = dim.requires
    if req is EvidenceRequirement.NONE:
        return EvidenceAvailability(can_evaluate=True)

    has_ref = item.has_reference()
    has_points = item.has_required_points()

    if req is EvidenceRequirement.REFERENCE:
        if has_ref:
            return EvidenceAvailability(can_evaluate=True)
        return EvidenceAvailability(
            can_evaluate=False,
            reason=(
                f"dimension '{dim.id}' requires a reference passage, but this item supplies none"
            ),
        )

    if req is EvidenceRequirement.REQUIRED_POINTS:
        if has_points:
            return EvidenceAvailability(can_evaluate=True)
        return EvidenceAvailability(
            can_evaluate=False,
            reason=(
                f"dimension '{dim.id}' requires a required_points list, but this item supplies none"
            ),
        )

    if req is EvidenceRequirement.REFERENCE_OR_POINTS:
        if has_ref or has_points:
            return EvidenceAvailability(can_evaluate=True)
        return EvidenceAvailability(
            can_evaluate=False,
            reason=(
                f"dimension '{dim.id}' requires a reference passage or a required_points "
                f"list, but this item supplies neither"
            ),
        )

    # Unreachable: EvidenceRequirement is a closed enum.
    return EvidenceAvailability(can_evaluate=False, reason=f"unknown requirement: {req}")
