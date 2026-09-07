"""Assemble a RunReport from evaluation results and render it.

Two outputs:
  * ``report.json`` — ``RunReport.model_dump(mode="json")``; the audit trail.
  * ``report.html`` — one self-contained file (inline CSS, no JS, no network).
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .models import DimensionType, Rubric
from .results import (
    DimensionResult,
    DimensionStatus,
    GateStatus,
    InstructionStatus,
    ItemResult,
    ReliabilityLabel,
    ReportSummary,
    RunMeta,
    RunReport,
    Verdict,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_JUDGED = {
    DimensionType.REFERENCE_GROUNDED,
    DimensionType.SPEC_GROUNDED,
    DimensionType.JUDGED,
}


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def _read_git_commit(start: Path) -> str | None:
    """Read the current commit from a .git directory WITHOUT running git or
    creating anything. Returns None if there is no repository."""
    for base in [start, *start.parents]:
        git = base / ".git"
        if not git.exists():
            continue
        try:
            head = (git / "HEAD").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if head.startswith("ref:"):
            ref = head[4:].strip()
            ref_path = git / ref
            if ref_path.is_file():
                return ref_path.read_text(encoding="utf-8").strip()[:12]
            packed = git / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(ref):
                        return line.split()[0][:12]
            return None
        return head[:12]  # detached HEAD
    return None


def build_summary(items: list[ItemResult]) -> ReportSummary:
    verdict_counts = {v.value: 0 for v in Verdict}
    gate_counts = {s.value: 0 for s in GateStatus}
    instruction_counts = {s.value: 0 for s in InstructionStatus}
    reliability_counts = {r.value: 0 for r in ReliabilityLabel}

    evaluated_judged = 0
    not_evaluated = 0
    unverified_evidence_dims = 0
    judge_error_runs = 0
    agreements: list[float] = []

    for item in items:
        verdict_counts[item.verdict.verdict.value] += 1
        if item.verdict_stability is not None:
            agreements.append(item.verdict_stability.agreement_fraction)

        for dim in item.dimensions:
            if dim.gate is not None:
                gate_counts[dim.gate.status.value] += 1
                for inst in dim.gate.instructions:
                    instruction_counts[inst.status.value] += 1
            if dim.type in _JUDGED:
                if dim.status is DimensionStatus.EVALUATED:
                    evaluated_judged += 1
                elif dim.status is DimensionStatus.NOT_EVALUATED:
                    not_evaluated += 1
                if dim.reliability_label is not None:
                    reliability_counts[dim.reliability_label.value] += 1
                if dim.evidence_any_unverified:
                    unverified_evidence_dims += 1
                judge_error_runs += dim.judge_error_count

    return ReportSummary(
        item_count=len(items),
        verdict_counts=verdict_counts,
        gate_status_counts=gate_counts,
        instruction_check_counts=instruction_counts,
        reliability_counts=reliability_counts,
        evaluated_judged_dimension_count=evaluated_judged,
        not_evaluated_dimension_count=not_evaluated,
        unverified_evidence_dimension_count=unverified_evidence_dims,
        judge_error_run_count=judge_error_runs,
        items_with_errors_count=sum(1 for i in items if i.errors),
        dataset_verdict_agreement=(round(statistics.fmean(agreements), 4) if agreements else None),
    )


def build_run_report(
    rubric: Rubric,
    items: list[ItemResult],
    *,
    dataset_path: str,
    provider: str,
    judge_model: str | None,
    judge_temperature: float | None,
    runs: int,
    command: str | None = None,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> RunReport:
    meta = RunMeta(
        harness_version=__version__,
        generated_at=generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
        rubric_id=rubric.id,
        rubric_title=rubric.title,
        rubric_version=rubric.version,
        dataset_path=dataset_path,
        dataset_item_count=len(items),
        provider=provider,
        judge_model=judge_model,
        judge_temperature=judge_temperature,
        runs=runs,
        command=command,
        git_commit=_read_git_commit(repo_root or Path.cwd()),
    )
    return RunReport(meta=meta, items=items, summary=build_summary(items))


# --------------------------------------------------------------------------- #
# Failure surfacing (used by the template's failures-first section)
# --------------------------------------------------------------------------- #


def item_failure_reasons(item: ItemResult) -> list[str]:
    """Every reason this item belongs in the failures-first section. Empty list
    == nothing wrong."""
    reasons: list[str] = []
    v = item.verdict.verdict
    if v is Verdict.FAIL:
        reasons.append("verdict: Fail")
    elif v is Verdict.NEEDS_WORK:
        reasons.append("verdict: Needs work")
    elif v is Verdict.UNRESOLVED:
        reasons.append("verdict: Unresolved")

    for dim in item.dimensions:
        if dim.gate is not None:
            if dim.gate.status is GateStatus.FAIL:
                failed = [
                    i.text for i in dim.gate.instructions if i.status is InstructionStatus.FAIL
                ]
                reasons.append(f"instruction-following gate failed: {'; '.join(failed)}")
            elif dim.gate.status is GateStatus.ERROR:
                reasons.append("instruction-following gate could not be evaluated (judge error)")
        if dim.type is DimensionType.DETERMINISTIC and dim.deterministic_passed is False:
            bad = [c.name for c in dim.checks if c.outcome.value == "fail"]
            reasons.append(
                f"deterministic check(s) failed in '{dim.dimension_id}': {', '.join(bad)}"
            )
        if dim.type in _JUDGED:
            if dim.status is DimensionStatus.NOT_EVALUATED:
                reasons.append(f"'{dim.dimension_id}' NOT evaluated: {dim.not_evaluated_reason}")
            if dim.evidence_any_unverified:
                reasons.append(
                    f"'{dim.dimension_id}': judge returned an UNVERIFIED evidence quote "
                    "(not found in the reference — possible judge hallucination)"
                )
            if dim.judge_error_count:
                reasons.append(f"'{dim.dimension_id}': {dim.judge_error_count} judge run(s) failed")
            if dim.reliability_label is ReliabilityLabel.UNRELIABLE:
                reasons.append(
                    f"'{dim.dimension_id}': judged scores are unreliable "
                    f"(stdev {dim.stdev}, disagreement {dim.pairwise_disagreement_rate})"
                )

    if item.verdict_stability is not None and item.verdict_stability.agreement_fraction < 1.0:
        st = item.verdict_stability
        reasons.append(
            f"verdict unstable across runs: {st.distribution} (agreement {st.agreement_fraction})"
        )
    return reasons


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

_METHODOLOGY = [
    "Reliability thresholds (STABLE / SOME_VARIANCE / UNRELIABLE) are configurable "
    "operational heuristics, not statistically validated boundaries. The raw "
    "per-run scores, mean, population standard deviation, min/max and pairwise "
    "disagreement rate are the source of truth and are shown alongside every label.",
    "LLM judges can be biased, inconsistent, or simply wrong. Treat a single score "
    "as an estimate, not ground truth.",
    "Evidence verification checks only whether the quoted span actually occurs in "
    "the supplied reference. It does NOT independently prove the underlying claim "
    "is true.",
    "When a judge returns an evidence quote that is not in the reference, the harness "
    "surfaces it as UNVERIFIED and possibly fabricated — it does not zero the score "
    "or hide the condition.",
    "Repeated judging measures judge-output consistency under THIS configuration "
    "(model, temperature, prompt, run count). It is not a formal statistical "
    "confidence interval.",
    "Instruction-following is judged once per item; judged rubric dimensions receive "
    "N runs. Per-run verdict variation therefore reflects only the judged-dimension "
    "scores.",
    "The dataset included with this project is entirely synthetic — invented "
    "organisations, people, facts, and scenarios — written to demonstrate evaluator "
    "behaviour.",
    "This project is NOT a model benchmark and produces no leaderboard. It evaluates "
    "supplied responses against an explicit rubric and reports how it did so.",
]


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2", "html.j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["fmt_num"] = _fmt_num
    return env


def _fmt_num(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _verdict_slug(verdict: str) -> str:
    return verdict.lower().replace(" ", "-")


def render_html(report: RunReport) -> str:
    env = _environment()
    template = env.get_template("report.html.j2")
    failures = {item.item_id: item_failure_reasons(item) for item in report.items}
    return template.render(
        report=report,
        failures=failures,
        methodology=_METHODOLOGY,
        verdict_slug=_verdict_slug,
        DimensionType=DimensionType,
        DimensionStatus=DimensionStatus,
        GateStatus=GateStatus,
        InstructionStatus=InstructionStatus,
        ReliabilityLabel=ReliabilityLabel,
        Verdict=Verdict,
        judged_types=_JUDGED,
    )


def write_report(report: RunReport, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "report.html"
    json_path = out / "report.json"
    html_path.write_text(render_html(report), encoding="utf-8")
    json_path.write_text(report.model_dump_json(indent=2, exclude_none=False), encoding="utf-8")
    return html_path, json_path


def dimension_is_failure(item: ItemResult, dim: DimensionResult) -> bool:
    """Small helper the template uses to auto-expand failing items."""
    return bool(item_failure_reasons(item))


__all__ = [
    "build_run_report",
    "build_summary",
    "item_failure_reasons",
    "render_html",
    "write_report",
]
