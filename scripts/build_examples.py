#!/usr/bin/env python3
"""Regenerate the committed example reports under examples/.

Run: ``python scripts/build_examples.py`` (after ``scripts/build_demo.py``).

Every example is produced deterministically from the offline mock provider with
a fixed timestamp and no git commit, so ``tests/test_report.py`` can byte-compare
the committed files against a fresh regeneration.
"""

from __future__ import annotations

from pathlib import Path

from rubric_eval.dataset import load_dataset
from rubric_eval.evaluate import safe_evaluate_item
from rubric_eval.providers.mock import MockProvider
from rubric_eval.report import build_run_report, render_html
from rubric_eval.rubric import load_rubric

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
MOCK = ROOT / "datasets" / "_mock_judgments.json"
FIXED_TIMESTAMP = "2026-01-01T00:00:00+00:00"

FAMILIES = [
    ("summarization", "rubrics/summarization_quality.yaml", "datasets/summarization.jsonl"),
    ("support-email", "rubrics/support_email_reply.yaml", "datasets/support_email.jsonl"),
    ("grounded-qa", "rubrics/grounded_qa.yaml", "datasets/grounded_qa.jsonl"),
]


def build_one(slug: str, rubric_rel: str, dataset_rel: str) -> tuple[str, str]:
    rubric = load_rubric(ROOT / rubric_rel)
    items = load_dataset(ROOT / dataset_rel)
    provider = MockProvider.from_file(MOCK)
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
        generated_at=FIXED_TIMESTAMP,
    )
    return render_html(report), report.model_dump_json(indent=2, exclude_none=False)


def main() -> None:
    EXAMPLES.mkdir(exist_ok=True)
    for slug, rubric_rel, dataset_rel in FAMILIES:
        html, js = build_one(slug, rubric_rel, dataset_rel)
        (EXAMPLES / f"report-{slug}.html").write_text(html, encoding="utf-8", newline="\n")
        (EXAMPLES / f"report-{slug}.json").write_text(js + "\n", encoding="utf-8", newline="\n")
        print(f"wrote examples/report-{slug}.html / .json")


if __name__ == "__main__":
    main()
