"""Rubric file loading + validation."""

from __future__ import annotations

import pytest

from rubric_eval.errors import RubricError
from rubric_eval.rubric import load_rubric


def test_valid_rubric_loads(write_file, minimal_rubric_yaml):
    p = write_file("r.yaml", minimal_rubric_yaml)
    rubric = load_rubric(p)
    assert rubric.id == "demo_rubric"
    assert rubric.gate_dimension() is not None
    assert len(rubric.deterministic_dimensions()) == 1
    assert len(rubric.judged_dimensions()) == 2


def test_missing_file(tmp_path):
    with pytest.raises(RubricError, match="not found"):
        load_rubric(tmp_path / "nope.yaml")


def test_malformed_yaml(write_file):
    p = write_file("bad.yaml", "id: x\n  : : :\n")
    with pytest.raises(RubricError, match="malformed YAML"):
        load_rubric(p)


def test_top_level_not_mapping(write_file):
    p = write_file("list.yaml", "- a\n- b\n")
    with pytest.raises(RubricError, match="must contain a YAML mapping"):
        load_rubric(p)


def test_empty_file(write_file):
    p = write_file("empty.yaml", "")
    with pytest.raises(RubricError, match="empty"):
        load_rubric(p)


def test_unknown_dimension_type(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
dimensions:
  - id: d
    type: telepathy
""",
    )
    with pytest.raises(RubricError, match="invalid rubric"):
        load_rubric(p)


def test_duplicate_dimension_id(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
dimensions:
  - {id: clarity, type: judged, anchors: {1: a, 5: b}}
  - {id: clarity, type: judged, anchors: {1: a, 5: b}}
""",
    )
    with pytest.raises(RubricError, match="duplicate dimension id 'clarity'"):
        load_rubric(p)


def test_judged_without_anchors(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
dimensions:
  - {id: clarity, type: judged}
""",
    )
    with pytest.raises(RubricError, match="requires 'anchors'"):
        load_rubric(p)


def test_anchor_outside_scale(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
dimensions:
  - {id: clarity, type: judged, anchors: {1: a, 5: b, 9: c}}
""",
    )
    with pytest.raises(RubricError, match="outside the scale"):
        load_rubric(p)


def test_anchor_endpoints_required(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
dimensions:
  - {id: clarity, type: judged, anchors: {2: a, 4: b}}
""",
    )
    with pytest.raises(RubricError, match="must include both scale endpoints"):
        load_rubric(p)


def test_invalid_scale_range(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 5, max: 1}
dimensions:
  - {id: clarity, type: judged, anchors: {1: a, 5: b}}
""",
    )
    with pytest.raises(RubricError, match="must be less than"):
        load_rubric(p)


def test_deterministic_negative_threshold(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
dimensions:
  - id: fmt
    type: deterministic
    rules:
      - {name: w, kind: max_word_count, value: -5}
""",
    )
    with pytest.raises(RubricError, match=">= 0"):
        load_rubric(p)


def test_two_gates_rejected(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
dimensions:
  - {id: g1, type: gate}
  - {id: g2, type: gate}
""",
    )
    with pytest.raises(RubricError, match="at most one 'gate'"):
        load_rubric(p)


def test_safety_dim_must_be_deterministic(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
verdict:
  safety_dimension_ids: [clarity]
dimensions:
  - {id: clarity, type: judged, anchors: {1: a, 5: b}}
""",
    )
    with pytest.raises(RubricError, match="not a 'deterministic' dimension"):
        load_rubric(p)


def test_unknown_top_level_key_rejected(write_file):
    p = write_file(
        "r.yaml",
        """
id: r
title: t
scale: {min: 1, max: 5}
mystery: 1
dimensions:
  - {id: clarity, type: judged, anchors: {1: a, 5: b}}
""",
    )
    with pytest.raises(RubricError, match="invalid rubric"):
        load_rubric(p)
