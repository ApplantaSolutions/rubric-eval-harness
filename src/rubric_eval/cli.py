"""Command-line interface.

    rubric-eval validate --rubric R [--dataset D]
    rubric-eval run --rubric R --dataset D [--provider mock|anthropic]
                    [--runs N] [--judge-temp T] [--mock-judgments FILE] [--out DIR]

With --out DIR the run writes DIR/report.html and DIR/report.json. Without it,
the JSON report is printed to stdout.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .dataset import load_dataset
from .errors import RubricEvalError
from .evaluate import safe_evaluate_item
from .providers.base import Provider
from .providers.mock import MockProvider
from .rubric import load_rubric

try:  # optional: load a .env for local runs
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _build_provider(args: argparse.Namespace) -> Provider:
    if args.provider == "mock":
        if args.mock_judgments:
            return MockProvider.from_file(args.mock_judgments)
        return MockProvider()
    if args.provider == "anthropic":
        from .providers.anthropic import AnthropicProvider

        return AnthropicProvider.from_env()
    raise RubricEvalError(f"unknown provider: {args.provider}")


def _cmd_validate(args: argparse.Namespace) -> int:
    rubric = load_rubric(args.rubric)
    print(f"rubric OK: {rubric.id} v{rubric.version} — {len(rubric.dimensions)} dimension(s)")
    if args.dataset:
        items = load_dataset(args.dataset)
        print(f"dataset OK: {len(items)} item(s)")
    return 0


def _reproduce_command(args: argparse.Namespace) -> str:
    parts = [
        "rubric-eval run",
        f"--rubric {args.rubric}",
        f"--dataset {args.dataset}",
        f"--provider {args.provider}",
    ]
    if args.runs is not None:
        parts.append(f"--runs {args.runs}")
    if args.judge_temp:
        parts.append(f"--judge-temp {args.judge_temp}")
    if args.mock_judgments:
        parts.append(f"--mock-judgments {args.mock_judgments}")
    if args.out:
        parts.append(f"--out {args.out}")
    return " ".join(parts)


def _cmd_run(args: argparse.Namespace) -> int:
    from .report import build_run_report, write_report

    rubric = load_rubric(args.rubric)
    items = load_dataset(args.dataset)
    provider = _build_provider(args)
    n_runs = args.runs if args.runs is not None else rubric.reliability.runs_default
    judge_model = getattr(provider, "model", None)

    results = [
        safe_evaluate_item(
            rubric, item, provider, runs=args.runs, judge_temperature=args.judge_temp
        )
        for item in items
    ]

    report = build_run_report(
        rubric,
        results,
        dataset_path=str(args.dataset),
        provider=provider.name,
        judge_model=judge_model,
        judge_temperature=args.judge_temp,
        runs=n_runs,
        command=_reproduce_command(args),
        repo_root=Path(__file__).resolve().parents[2],
    )

    if args.out:
        html_path, json_path = write_report(report, args.out)
        print(f"wrote {html_path}")
        print(f"wrote {json_path}")
    else:
        print(report.model_dump_json(indent=2))

    counts = report.summary.verdict_counts
    summary = " · ".join(f"{k}: {v}" for k, v in counts.items() if v)
    print(f"\n{report.summary.item_count} item(s) — {summary}", file=sys.stderr)
    errored = [r.item_id for r in results if r.errors]
    if errored:
        print(f"items with errors: {', '.join(errored)}", file=sys.stderr)
    if report.summary.unverified_evidence_dimension_count:
        print(
            f"UNVERIFIED judge evidence in "
            f"{report.summary.unverified_evidence_dimension_count} dimension(s)",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rubric-eval", description=__doc__)
    parser.add_argument("--version", action="version", version=f"rubric-eval {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="validate a rubric (and optionally a dataset)")
    p_val.add_argument("--rubric", required=True)
    p_val.add_argument("--dataset")
    p_val.set_defaults(func=_cmd_validate)

    p_run = sub.add_parser("run", help="evaluate a dataset against a rubric")
    p_run.add_argument("--rubric", required=True)
    p_run.add_argument("--dataset", required=True)
    p_run.add_argument(
        "--provider",
        choices=["mock", "anthropic"],
        default=os.environ.get("EVAL_PROVIDER", "mock"),
    )
    p_run.add_argument("--runs", type=int, default=None)
    p_run.add_argument(
        "--judge-temp",
        type=float,
        default=float(os.environ.get("EVAL_JUDGE_TEMPERATURE", "0.0")),
    )
    p_run.add_argument("--mock-judgments", default=None)
    p_run.add_argument("--out", default=None)
    p_run.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except RubricEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
