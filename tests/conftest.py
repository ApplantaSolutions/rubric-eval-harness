"""Shared test fixtures. Every test in this suite runs offline: no API key,
no network. All content here is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def write_file(tmp_path: Path):
    def _write(name: str, content: str) -> Path:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    return _write


@pytest.fixture
def minimal_rubric_dict() -> dict:
    """A valid rubric covering a gate, a deterministic dimension, a
    reference-grounded dimension, and a plain judged dimension."""
    return {
        "id": "demo_rubric",
        "title": "Demo rubric",
        "scale": {"min": 1, "max": 5},
        "dimensions": [
            {
                "id": "instruction_following",
                "type": "gate",
                "global_checks": [
                    {
                        "text": "Response is at most 40 words",
                        "method": "deterministic",
                        "rule": {"name": "len", "kind": "max_word_count", "value": 40},
                    },
                    {"text": "No opinion or editorializing", "method": "judge"},
                ],
            },
            {
                "id": "format",
                "type": "deterministic",
                "rules": [
                    {"name": "no_headers", "kind": "forbidden_regex", "pattern": r"(?m)^\s*#"},
                ],
            },
            {
                "id": "faithfulness",
                "type": "reference_grounded",
                "anchors": {5: "fully supported", 3: "mostly supported", 1: "unsupported"},
            },
            {
                "id": "clarity",
                "type": "judged",
                "anchors": {5: "very clear", 3: "ok", 1: "unclear"},
            },
        ],
    }


@pytest.fixture
def minimal_rubric_yaml(minimal_rubric_dict: dict) -> str:
    return yaml.safe_dump(minimal_rubric_dict, sort_keys=False)


@pytest.fixture
def sample_item_dict() -> dict:
    return {
        "id": "item-1",
        "task": "Summarize the passage in two sentences.",
        "candidate_response": "The transit study recommends adding two bus routes. It expects a ten percent ridership gain.",
        "instructions": ["Two sentences or fewer", "Neutral tone"],
        "reference": (
            "The Aldergrove Regional Transit study recommends adding two new bus routes "
            "to the north corridor. Modelling projects a ten percent ridership gain within "
            "the first year."
        ),
        "required_points": ["the recommendation", "the projected ridership change"],
        "scenario": "excellent",
    }
