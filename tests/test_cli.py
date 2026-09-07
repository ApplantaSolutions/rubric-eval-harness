"""Minimal CLI smoke tests (offline, mock provider)."""

from __future__ import annotations

import json

import pytest

from rubric_eval.cli import main

_RUBRIC = """
id: cli_demo
title: CLI demo
scale: {min: 1, max: 5}
reliability: {runs_default: 2}
dimensions:
  - id: gate
    type: gate
    global_checks:
      - {text: "<= 30 words", method: deterministic, rule: {name: w, kind: max_word_count, value: 30}}
  - id: clarity
    type: judged
    anchors: {1: unclear, 5: clear}
"""

_DATASET = "\n".join(
    json.dumps(row)
    for row in [
        {"id": "a", "task": "t", "candidate_response": "a short clear answer"},
        {"id": "b", "task": "t", "candidate_response": "another short answer"},
    ]
)


@pytest.fixture
def files(write_file):
    r = write_file("r.yaml", _RUBRIC)
    d = write_file("d.jsonl", _DATASET + "\n")
    return r, d


def test_validate_ok(files, capsys):
    r, d = files
    assert main(["validate", "--rubric", str(r), "--dataset", str(d)]) == 0
    out = capsys.readouterr().out
    assert "rubric OK" in out
    assert "dataset OK: 2 item(s)" in out


def test_validate_bad_rubric_returns_2(write_file, capsys):
    bad = write_file("bad.yaml", "id: x\ntitle: y\nscale: {min: 5, max: 1}\ndimensions: []\n")
    assert main(["validate", "--rubric", str(bad)]) == 2
    assert "error:" in capsys.readouterr().err


def test_run_mock_writes_report_dir(files, tmp_path, capsys):
    r, d = files
    out = tmp_path / "report"
    rc = main(
        ["run", "--rubric", str(r), "--dataset", str(d), "--provider", "mock", "--out", str(out)]
    )
    assert rc == 0
    assert (out / "report.html").is_file()
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert payload["meta"]["provider"] == "mock"
    assert payload["meta"]["runs"] == 2
    assert len(payload["items"]) == 2
    assert {i["item_id"] for i in payload["items"]} == {"a", "b"}


def test_run_mock_with_judgments_file(files, write_file, capsys):
    r, d = files
    j = write_file(
        "j.json",
        json.dumps(
            {
                "a::__gate__": {"results": [{"index": 0, "status": "pass", "rationale": "ok"}]},
                "a::clarity": {"score": 5, "rationale": "clear", "evidence_quote": ""},
                "b::__gate__": {"results": [{"index": 0, "status": "pass", "rationale": "ok"}]},
                "b::clarity": {"score": 3, "rationale": "ok", "evidence_quote": ""},
            }
        ),
    )
    rc = main(
        [
            "run",
            "--rubric",
            str(r),
            "--dataset",
            str(d),
            "--provider",
            "mock",
            "--mock-judgments",
            str(j),
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    verdicts = {i["item_id"]: i["verdict"]["verdict"] for i in payload["items"]}
    assert verdicts["a"] == "Excellent"
    assert verdicts["b"] == "Acceptable"


def test_version():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
