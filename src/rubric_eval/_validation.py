"""Shared helper for turning a pydantic ValidationError into readable lines."""

from __future__ import annotations

from pydantic import ValidationError


def format_validation_error(exc: ValidationError) -> str:
    lines: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)
