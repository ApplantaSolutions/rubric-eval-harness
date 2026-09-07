"""Load and validate a JSONL evaluation dataset.

One evaluation item per line. Blank lines are ignored. Malformed JSON, invalid
items, duplicate ids, and empty datasets all raise :class:`DatasetError` with a
``path:line`` prefix. Nothing is silently skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ._validation import format_validation_error
from .errors import DatasetError


class EvalItem(BaseModel):
    """One thing to evaluate: a task, the model's response, and any evidence."""

    model_config = ConfigDict(extra="forbid")

    id: str
    task: str
    candidate_response: str
    instructions: list[str] = Field(default_factory=list)
    reference: str | None = None
    required_points: list[str] = Field(default_factory=list)
    scenario: str | None = None
    author_note: str | None = None

    def has_reference(self) -> bool:
        return self.reference is not None and self.reference.strip() != ""

    def has_required_points(self) -> bool:
        return len(self.required_points) > 0


def load_dataset(path: str | Path) -> list[EvalItem]:
    p = Path(path)
    if not p.is_file():
        raise DatasetError(f"dataset file not found: {p}")

    items: list[EvalItem] = []
    seen_ids: set[str] = set()

    for lineno, raw_line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(
                f"{p}:{lineno}: malformed JSON: {exc.msg} (column {exc.colno})"
            ) from exc

        if not isinstance(obj, dict):
            raise DatasetError(
                f"{p}:{lineno}: each line must be a JSON object (got {type(obj).__name__})"
            )

        try:
            item = EvalItem.model_validate(obj)
        except ValidationError as exc:
            raise DatasetError(
                f"{p}:{lineno}: invalid evaluation item:\n{format_validation_error(exc)}"
            ) from exc

        if item.id in seen_ids:
            raise DatasetError(f"{p}:{lineno}: duplicate item id '{item.id}'")
        seen_ids.add(item.id)
        items.append(item)

    if not items:
        raise DatasetError(f"{p}: dataset is empty (no evaluation items found)")

    return items
