"""JSONL dataset loading + validation."""

from __future__ import annotations

import json

import pytest

from rubric_eval.dataset import load_dataset
from rubric_eval.errors import DatasetError

_GOOD = {
    "id": "a-1",
    "task": "do the thing",
    "candidate_response": "did the thing",
}


def test_valid_jsonl_loads(write_file):
    lines = [json.dumps(_GOOD), json.dumps({**_GOOD, "id": "a-2"})]
    p = write_file("d.jsonl", "\n".join(lines) + "\n")
    items = load_dataset(p)
    assert [i.id for i in items] == ["a-1", "a-2"]
    assert items[0].reference is None
    assert items[0].required_points == []


def test_blank_lines_ignored(write_file):
    p = write_file("d.jsonl", "\n" + json.dumps(_GOOD) + "\n\n\n")
    assert len(load_dataset(p)) == 1


def test_missing_file(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        load_dataset(tmp_path / "missing.jsonl")


def test_malformed_json_reports_line(write_file):
    p = write_file("d.jsonl", json.dumps(_GOOD) + "\n{ not json\n")
    with pytest.raises(DatasetError, match=r"d\.jsonl:2: malformed JSON"):
        load_dataset(p)


def test_missing_candidate_response_reports_line(write_file):
    bad = {"id": "x", "task": "t"}
    p = write_file("d.jsonl", json.dumps(_GOOD) + "\n" + json.dumps(bad) + "\n")
    with pytest.raises(DatasetError, match=r"d\.jsonl:2: invalid evaluation item"):
        load_dataset(p)


def test_missing_id_rejected(write_file):
    bad = {"task": "t", "candidate_response": "r"}
    p = write_file("d.jsonl", json.dumps(bad) + "\n")
    with pytest.raises(DatasetError, match="invalid evaluation item"):
        load_dataset(p)


def test_unknown_field_rejected(write_file):
    bad = {**_GOOD, "temperature": 0.7}
    p = write_file("d.jsonl", json.dumps(bad) + "\n")
    with pytest.raises(DatasetError, match="invalid evaluation item"):
        load_dataset(p)


def test_duplicate_id_reports_line(write_file):
    p = write_file("d.jsonl", json.dumps(_GOOD) + "\n" + json.dumps(_GOOD) + "\n")
    with pytest.raises(DatasetError, match=r"d\.jsonl:2: duplicate item id 'a-1'"):
        load_dataset(p)


def test_empty_dataset_rejected(write_file):
    p = write_file("d.jsonl", "\n\n   \n")
    with pytest.raises(DatasetError, match="dataset is empty"):
        load_dataset(p)


def test_non_object_line_rejected(write_file):
    p = write_file("d.jsonl", "[1, 2, 3]\n")
    with pytest.raises(DatasetError, match="must be a JSON object"):
        load_dataset(p)


def test_optional_reference_and_points(write_file):
    item = {
        **_GOOD,
        "reference": "the passage",
        "required_points": ["p1", "p2"],
        "instructions": ["be brief"],
    }
    p = write_file("d.jsonl", json.dumps(item) + "\n")
    loaded = load_dataset(p)[0]
    assert loaded.has_reference() is True
    assert loaded.has_required_points() is True
    assert loaded.instructions == ["be brief"]


def test_whitespace_only_reference_is_not_a_reference(write_file):
    item = {**_GOOD, "reference": "   "}
    p = write_file("d.jsonl", json.dumps(item) + "\n")
    assert load_dataset(p)[0].has_reference() is False
