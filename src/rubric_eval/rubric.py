"""Load and validate a rubric from a YAML file."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ._validation import format_validation_error
from .errors import RubricError
from .models import Rubric


def load_rubric(path: str | Path) -> Rubric:
    """Read *path* and return a validated :class:`Rubric`.

    Raises :class:`RubricError` with a message that names the offending field
    for anything malformed. Never silently repairs.
    """
    p = Path(path)
    if not p.is_file():
        raise RubricError(f"rubric file not found: {p}")

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RubricError(f"{p}: malformed YAML: {exc}") from exc

    if raw is None:
        raise RubricError(f"{p}: rubric file is empty")
    if not isinstance(raw, dict):
        raise RubricError(
            f"{p}: rubric file must contain a YAML mapping at the top level "
            f"(got {type(raw).__name__})"
        )

    try:
        return Rubric.model_validate(raw)
    except ValidationError as exc:
        raise RubricError(f"{p}: invalid rubric:\n{format_validation_error(exc)}") from exc
