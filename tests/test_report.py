"""Report assembly, JSON round-trip, HTML rendering, and the shipped demo."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from rubric_eval.cli import main as cli_main
from rubric_eval.dataset import load_dataset
from rubric_eval.evaluate import safe_evaluate_item
from rubric_eval.providers.mock import MockProvider
from rubric_eval.report import build_run_report, item_failure_reasons, render_html
from rubric_eval.results import RunReport
from rubric_eval.rubric import load_rubric

ROOT = Path(__file__).resolve().parent.parent
MOCK_JUDGMENTS = ROOT / "datasets" / "_mock_judgments.json"
FIXED_TS = "2026-01-01T00:00:00+00:00"

FAMILIES = {
    "summarization": ("rubrics/summarization_quality.yaml", "datasets/summarization.jsonl"),
    "support-email": ("rubrics/support_email_reply.yaml", "datasets/support_email.jsonl"),
    "grounded-qa": ("rubrics/grounded_qa.yaml", "datasets/grounded_qa.jsonl"),
}


def _run_family(slug: str) -> tuple[RunReport, str]:
    rubric_rel, dataset_rel = FAMILIES[slug]
    rubric = load_rubric(ROOT / rubric_rel)
    items = load_dataset(ROOT / dataset_rel)
    provider = MockProvider.from_file(MOCK_JUDGMENTS)
    results = [safe_evaluate_item(rubric, it, provider, runs=None) for it in items]
    command = (
        f"rubric-eval run --rubric {rubric_rel} --dataset {dataset_rel} "
        f"--provider mock --mock-judgments datasets/_mock_judgments.json "
        f"--out examples/"
    )
    report = build_run_report(
        rubric,
        results,
        dataset_path=dataset_rel,
        provider="mock",
        judge_model=None,
        judge_temperature=0.0,
        runs=rubric.reliability.runs_default,
        command=command,
        repo_root=Path("/nonexistent-so-no-git-commit"),
        generated_at=FIXED_TS,
    )
    return report, render_html(report)


@pytest.fixture(scope="module")
def grounded():
    return _run_family("grounded-qa")


# --------------------------------------------------------------------------- #
# Shipped files load
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("slug", list(FAMILIES))
def test_shipped_rubric_loads(slug):
    rubric_rel, _ = FAMILIES[slug]
    rubric = load_rubric(ROOT / rubric_rel)
    assert rubric.dimensions


@pytest.mark.parametrize("slug", list(FAMILIES))
def test_shipped_dataset_loads(slug):
    _, dataset_rel = FAMILIES[slug]
    items = load_dataset(ROOT / dataset_rel)
    assert len(items) >= 3


def test_demo_totals_about_twelve_items():
    total = sum(len(load_dataset(ROOT / d)) for _, d in FAMILIES.values())
    assert total == 12


# --------------------------------------------------------------------------- #
# Schema + JSON round-trip
# --------------------------------------------------------------------------- #


def test_run_report_schema(grounded):
    report, _ = grounded
    assert report.meta.harness_version
    assert report.meta.generated_at == FIXED_TS
    assert report.meta.git_commit is None
    assert report.summary.item_count == len(report.items)
    # every verdict value is a key in the distribution (nothing folded away)
    assert set(report.summary.verdict_counts) >= {
        "Fail",
        "Needs work",
        "Acceptable",
        "Excellent",
        "Unresolved",
    }


def test_json_round_trip(grounded):
    report, _ = grounded
    text = report.model_dump_json(indent=2)
    restored = RunReport.model_validate_json(text)
    assert restored.model_dump() == report.model_dump()


def test_summary_does_not_hide_failures(grounded):
    report, _ = grounded
    s = report.summary
    # grounded-qa: 2 Needs work, gqa-hallucinated has unverified evidence,
    # gqa-unstable is UNRELIABLE and unstable.
    assert s.verdict_counts["Needs work"] == 2
    assert s.unverified_evidence_dimension_count == 1
    assert s.reliability_counts["unreliable"] == 1
    assert s.dataset_verdict_agreement is not None and s.dataset_verdict_agreement < 1.0


# --------------------------------------------------------------------------- #
# HTML content
# --------------------------------------------------------------------------- #


def test_html_is_a_document(grounded):
    _, html = grounded
    assert html.lstrip().startswith("<!doctype html>")
    assert "</html>" in html


def test_every_item_id_appears(grounded):
    report, html = grounded
    for item in report.items:
        assert f'id="item-{item.item_id}"' in html
        assert item.item_id in html


def test_expected_verdicts_appear(grounded):
    _, html = grounded
    assert "gqa-strong" in html and "Excellent" in html
    assert "Needs work" in html  # gqa-omission, gqa-hallucinated


def test_failures_first_section_populated(grounded):
    report, html = grounded
    # the failures-first block names each flagged item before the per-item detail
    ff = html.split("Failures first", 1)[1].split("Per-item detail", 1)[0]
    flagged = [i.item_id for i in report.items if item_failure_reasons(i)]
    assert flagged, "grounded-qa must have flagged items"
    for item_id in flagged:
        assert item_id in ff
    # gqa-strong is clean and must NOT be listed as a failure
    assert "gqa-strong" not in ff


def test_unverified_evidence_is_visually_surfaced(grounded):
    _, html = grounded
    # the hallucinated-evidence item must be loud about it
    assert "UNVERIFIED" in html
    assert "possible judge hallucination" in html
    assert "ev-bad" in html  # the red style class is actually used
    # and the score is still shown (not zeroed) — faithfulness mean ~3.8 for gqa-hallucinated
    assert "gqa-hallucinated" in html


def test_reliability_statistics_rendered(grounded):
    _, html = grounded
    assert "Raw statistics" in html
    assert "pairwise disagreement" in html
    assert "configurable operational heuristics" in html
    # the unreliable dimension's raw numbers are present
    assert "[5, 3, 5, 2, 5]" in html  # gqa-unstable faithfulness raw scores


def test_verdict_stability_rendered(grounded):
    _, html = grounded
    assert "Verdict-stability summary" in html
    assert "Verdict stability" in html
    assert "0.8" in html  # gqa-unstable agreement fraction


def test_methodology_points_present(grounded):
    _, html = grounded
    for phrase in [
        "not statistically validated boundaries",
        "can be biased, inconsistent, or",
        "does NOT independently prove",
        "entirely synthetic",
        "NOT a model benchmark",
        "Instruction-following is judged once",
    ]:
        assert phrase in html


def test_no_external_resource_in_html(grounded):
    _, html = grounded
    lowered = html.lower()
    for banned in [
        "http://",
        "https://",
        "<script",
        "src=",
        "@import",
        "cdn",
        "googleapis",
        "integrity=",
    ]:
        assert banned not in lowered, f"generated HTML must not reference {banned!r}"


def test_retry_marker_shown_for_se_retry():
    _, html = _run_family("support-email")
    assert "(retry)" in html  # se-retry recovered on attempt 2 on every run


def test_not_evaluated_is_shown_not_zeroed():
    report, html = _run_family("support-email")
    assert "NOT EVALUATED" in html
    assert "was NOT scored zero" in html
    je = next(i for i in report.items if i.item_id == "se-judgefail")
    faith = next(d for d in je.dimensions if d.dimension_id == "faithfulness")
    assert faith.status.value == "not_evaluated"
    assert faith.mean is None


# --------------------------------------------------------------------------- #
# Committed examples are reproducible
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("slug", list(FAMILIES))
def test_committed_examples_match_regeneration(slug):
    report, html = _run_family(slug)
    committed_html = (ROOT / "examples" / f"report-{slug}.html").read_text(encoding="utf-8")
    committed_json = (ROOT / "examples" / f"report-{slug}.json").read_text(encoding="utf-8")
    assert html == committed_html, (
        f"examples/report-{slug}.html is stale — run scripts/build_examples.py"
    )
    assert json.loads(committed_json) == json.loads(report.model_dump_json())


# --------------------------------------------------------------------------- #
# CLI --out
# --------------------------------------------------------------------------- #


def test_cli_out_writes_both_artifacts(tmp_path):
    out = tmp_path / "report"
    rc = cli_main(
        [
            "run",
            "--rubric",
            str(ROOT / "rubrics" / "grounded_qa.yaml"),
            "--dataset",
            str(ROOT / "datasets" / "grounded_qa.jsonl"),
            "--provider",
            "mock",
            "--mock-judgments",
            str(MOCK_JUDGMENTS),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert (out / "report.html").is_file()
    assert (out / "report.json").is_file()
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert payload["meta"]["provider"] == "mock"
    assert len(payload["items"]) == 4
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "https://" not in html
    # reproduce command is recorded
    assert "--out" in payload["meta"]["command"]


def test_cli_out_preserves_error_and_not_evaluated_state(tmp_path):
    out = tmp_path / "r"
    cli_main(
        [
            "run",
            "--rubric",
            str(ROOT / "rubrics" / "support_email_reply.yaml"),
            "--dataset",
            str(ROOT / "datasets" / "support_email.jsonl"),
            "--provider",
            "mock",
            "--mock-judgments",
            str(MOCK_JUDGMENTS),
            "--out",
            str(out),
        ]
    )
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    je = next(i for i in payload["items"] if i["item_id"] == "se-judgefail")
    assert je["errors"]
    faith = next(d for d in je["dimensions"] if d["dimension_id"] == "faithfulness")
    assert faith["status"] == "not_evaluated"
    assert faith["mean"] is None
    assert faith["judge_error_count"] == 5


def test_generated_html_has_no_script_tag_anywhere():
    for slug in FAMILIES:
        _, html = _run_family(slug)
        assert not re.search(r"<script", html, re.IGNORECASE)
