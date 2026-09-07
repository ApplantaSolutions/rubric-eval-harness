#!/usr/bin/env python3
"""Generate the synthetic demo dataset + mock judgments, and self-check them.

Run: ``python scripts/build_demo.py``

Writes:
  datasets/summarization.jsonl
  datasets/support_email.jsonl
  datasets/grounded_qa.jsonl
  datasets/_mock_judgments.json

All content here is invented for this project — fictional organisations, people,
facts, emails, and scenarios. Nothing is derived from real data or any other
project. This script exists so the demo can be regenerated and audited.

The asserts at the bottom verify that the authored responses actually produce
the intended deterministic outcomes (word/sentence counts, regex) and that every
"verified" evidence quote is a real substring of its reference.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"

# --------------------------------------------------------------------------- #
# Shared invented references
# --------------------------------------------------------------------------- #

TRANSIT_PASSAGE = (
    "The Aldergrove Regional Transit board approved a pilot that adds two express "
    "bus routes on the north corridor beginning in March. Staff modelling projects "
    "a ten percent ridership increase in the first year and an operating break-even "
    "by year three. The board asked staff to report back on wheelchair-accessible "
    "boarding at the two new terminals."
)

BUDGET_PASSAGE = (
    "The Ferndale School District's 2027 budget raises per-pupil spending by four "
    "percent and funds a new after-school tutoring programme at all eight elementary "
    "schools. The board deferred a decision on replacing the district's aging bus "
    "fleet to the spring session."
)

RETURN_POLICY = (
    "Northwind Widgets return policy: items may be returned within 14 days of "
    "delivery for store credit. Defective items reported within 30 days are "
    "replaced at no cost. Cash or card refunds are not offered. Replacement orders "
    "ship within 3 business days of approval."
)

FERRY_CONTEXT = (
    "The Brightline Ferry ran 1,240 crossings in 2026, up from 1,090 in 2025. "
    "On-time performance was 91 percent in 2026. The operator attributed the "
    "improvement to a new scheduling system installed in January 2026."
)

GREENLINE_CONTEXT = (
    "Greenline Logistics reduced its fleet emissions by 18 percent in 2026 and "
    "cut fuel spend by 620,000 dollars. The company also switched 40 percent of "
    "last-mile deliveries to electric cargo bikes."
)

WAREHOUSE_CONTEXT = (
    "Aurora Nutrition Co. lists three warehouse sites: Cedar Falls (opened 2019), "
    "Marlow (opened 2022), and Pinehurst (opened 2024). The Marlow site is the "
    "only one with automated cold storage."
)

TIDEWATER_CONTEXT = (
    "Tidewater Coffee opened its first roastery in Bellhaven in 2021. It now "
    "supplies 30 cafes across the region. The company has not disclosed its "
    "annual revenue."
)

# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #

SUMMARIZATION = [
    {
        "id": "sum-strong",
        "task": "Summarise the passage below in three sentences or fewer. Neutral tone.\n\n"
        + TRANSIT_PASSAGE,
        "candidate_response": (
            "The Aldergrove Regional Transit board approved a pilot adding two "
            "express bus routes on the north corridor from March. Modelling projects "
            "a ten percent ridership increase in the first year and operating "
            "break-even by year three. The board also requested a follow-up on "
            "accessible boarding at the new terminals."
        ),
        "reference": TRANSIT_PASSAGE,
        "required_points": ["the two new express routes", "the projected ridership increase"],
        "scenario": "strong response — faithful, within limits, covers the required points",
    },
    {
        "id": "sum-wordy",
        "task": "Summarise the passage below in three sentences or fewer. Neutral tone.\n\n"
        + TRANSIT_PASSAGE,
        "candidate_response": (
            "The Aldergrove Regional Transit board has approved a new pilot programme "
            "that will add two additional express bus routes running along the north "
            "corridor of the city, with service scheduled to begin at some point in "
            "March of next year, and the internal modelling work that staff carried "
            "out projects that there will be roughly a ten percent increase in "
            "overall ridership during the first full year of operation, with the new "
            "routes reaching an operating break-even point by the third year of the "
            "programme."
        ),
        "reference": TRANSIT_PASSAGE,
        "required_points": ["the two new express routes", "the projected ridership increase"],
        "scenario": "deterministic instruction failure — exceeds the 60-word limit",
        "author_note": "Faithful and clear, but fails a hard length rule; verdict should be Fail.",
    },
    {
        "id": "sum-opinion-drift",
        "task": "Summarise the passage below in three sentences or fewer. Neutral tone.\n\n"
        + BUDGET_PASSAGE,
        "candidate_response": (
            "The Ferndale School District's 2027 budget raises per-pupil spending by "
            "four percent and funds after-school tutoring at all eight elementary "
            "schools. Frankly this is a long-overdue and welcome investment in "
            "students. The board put off replacing the old bus fleet until spring."
        ),
        "reference": BUDGET_PASSAGE,
        "required_points": ["the per-pupil spending change", "the new tutoring programme"],
        "scenario": "judged instruction failure (editorialising) + judge disagreement on faithfulness",
    },
    {
        "id": "sum-noref",
        "task": "Summarise the customer's message below in three sentences or fewer. Neutral tone.\n\n"
        "(customer message omitted from this record)",
        "candidate_response": (
            "The customer says their delivery arrived two days late and one box was "
            "damaged. They want a partial credit and confirmation that the "
            "replacement has shipped. They also ask to be moved to a later delivery "
            "window from now on."
        ),
        "scenario": "no reference or required points supplied — faithfulness and completeness cannot be scored",
        "author_note": "Demonstrates NOT_EVALUATED: two judged dimensions are excluded, not zeroed.",
    },
]

SUPPORT_EMAIL = [
    {
        "id": "se-strong",
        "task": "Write a reply to the customer below. Ticket #4021. Be warm and specific.\n\n"
        "Customer: my blender arrived with a cracked jug.",
        "candidate_response": (
            "Hi Dana, thanks for flagging ticket #4021. I'm sorry the blender arrived "
            "with a cracked jug. Because you reported it within 30 days, we'll replace "
            "it at no cost, and the replacement ships within 3 business days of "
            "approval. I've approved it now, so a tracking number should reach you "
            "shortly. - Priya, Northwind Support"
        ),
        "reference": RETURN_POLICY,
        "scenario": "strong response — accurate to policy, acknowledges the issue, gives a next step",
    },
    {
        "id": "se-overpromise",
        "task": "Write a reply to the customer below. Ticket #4055.\n\n"
        "Customer: the kettle stopped working after a week.",
        "candidate_response": (
            "Hi Marcus, so sorry about ticket #4055 and the trouble with your kettle. "
            "Don't worry - I'll refund you the full amount today and you'll see it "
            "back on your card within a few days. We guarantee you'll be happy."
        ),
        "reference": RETURN_POLICY,
        "scenario": "policy violation — promises a card refund and a guarantee the policy does not allow",
        "author_note": "policy_safety is a safety dimension; its failure caps the verdict at Needs work.",
    },
    {
        "id": "se-retry",
        "task": "Write a reply to the customer below. Ticket #4102.\n\n"
        "Customer: I'd like to return an unopened mixer.",
        "candidate_response": (
            "Hi Sofia - thanks for reaching out on ticket #4102. You're within the "
            "14-day window, so I can set up a return for store credit. Once we "
            "receive the item, the credit posts to your account. Let me know if "
            "you'd like the prepaid label."
        ),
        "reference": RETURN_POLICY,
        "scenario": "the faithfulness judge's first response was malformed on every run; the single retry succeeded",
    },
    {
        "id": "se-judgefail",
        "task": "Write a reply to the customer below. Ticket #4200.\n\n"
        "Customer: my coffee grinder is defective, bought it three weeks ago.",
        "candidate_response": (
            "Hi Aki, thanks for the note on ticket #4200. Your grinder is a defective "
            "unit reported within 30 days, so we'll send a free replacement. It ships "
            "within 3 business days once approved, and I've approved it now."
        ),
        "reference": RETURN_POLICY,
        "scenario": "the faithfulness judge failed on every run (simulated outage) — the dimension is not scored, not zeroed",
    },
]

GROUNDED_QA = [
    {
        "id": "gqa-strong",
        "task": "Which Aurora Nutrition warehouse has automated cold storage? Answer in one sentence.\n\n"
        "Context: " + WAREHOUSE_CONTEXT,
        "candidate_response": (
            "The Marlow site is the only Aurora Nutrition warehouse with automated cold storage."
        ),
        "reference": WAREHOUSE_CONTEXT,
        "required_points": ["names the Marlow site"],
        "scenario": "strong response — answers exactly what the context supports, one sentence",
    },
    {
        "id": "gqa-unstable",
        "task": "How many crossings did the Brightline Ferry run in 2026, and what did the "
        "operator credit for the on-time improvement? Answer in two sentences or fewer.\n\n"
        "Context: " + FERRY_CONTEXT,
        "candidate_response": (
            "The Brightline Ferry ran 1,240 crossings in 2026. The operator credited a "
            "new scheduling system installed that January for the better on-time "
            "performance."
        ),
        "reference": FERRY_CONTEXT,
        "required_points": [
            "the 2026 crossing count",
            "the reason credited for the on-time improvement",
        ],
        "scenario": "verdict instability — the faithfulness judge's score swings run to run, flipping the item verdict",
    },
    {
        "id": "gqa-omission",
        "task": "By how much did Greenline cut fuel spend in 2026, and what share of last-mile "
        "deliveries went electric? Answer in two sentences or fewer.\n\n"
        "Context: " + GREENLINE_CONTEXT,
        "candidate_response": (
            "Greenline Logistics cut its fuel spend by about 620,000 dollars in 2026."
        ),
        "reference": GREENLINE_CONTEXT,
        "required_points": [
            "the fuel spend reduction amount",
            "the electric last-mile delivery share",
        ],
        "scenario": "omits required information — answers only the first half of a two-part question",
    },
    {
        "id": "gqa-hallucinated",
        "task": "What was Tidewater Coffee's annual revenue in 2026? Answer in one sentence.\n\n"
        "Context: " + TIDEWATER_CONTEXT,
        "candidate_response": (
            "Tidewater Coffee reported approximately 4.2 million dollars in annual "
            "revenue for 2026."
        ),
        "reference": TIDEWATER_CONTEXT,
        "required_points": ["states whether the context gives the revenue"],
        "scenario": "hallucination — the context does not contain the answer, and the judge also returns a fabricated supporting quote",
        "author_note": "The judge is confidently wrong AND cites a quote that is not in the context. "
        "The harness surfaces the fabricated quote and keeps the judge's score visible rather than silently zeroing it.",
    },
]

# --------------------------------------------------------------------------- #
# Mock judgments — deterministic offline demo
# --------------------------------------------------------------------------- #


def _dim(score, rationale, quote=""):
    return {"score": score, "rationale": rationale, "evidence_quote": quote}


def _per_run(*entries):
    return {"per_run": list(entries)}


def _gate(*rows):
    return {"results": [dict(index=i, **row) for i, row in enumerate(rows)]}


def _pass(rationale):
    return {"status": "pass", "rationale": rationale, "evidence_quote": ""}


def _fail(rationale, quote=""):
    return {"status": "fail", "rationale": rationale, "evidence_quote": quote}


MOCK = {
    # ---- summarization ----
    "sum-strong::__gate__": _gate(_pass("Neutral throughout; no first-person opinion.")),
    "sum-strong::faithfulness": _per_run(
        _dim(5, "Every claim maps to the passage.", "two express bus routes on the north corridor"),
        _dim(5, "Fully supported.", "a ten percent ridership increase in the first year"),
        _dim(5, "Fully supported.", "two express bus routes on the north corridor"),
        _dim(5, "Fully supported.", "an operating break-even\nby year three"),
        _dim(5, "Fully supported.", "two express bus routes on the north corridor"),
    ),
    "sum-strong::completeness": _dim(5, "Covers both required points."),
    "sum-strong::clarity": _dim(5, "Well ordered and plain."),
    "sum-wordy::__gate__": _gate(_pass("No opinion, though very long.")),
    "sum-wordy::faithfulness": _dim(
        5, "Faithful to the passage.", "two express bus routes on the north corridor"
    ),
    "sum-wordy::completeness": _dim(5, "Covers both required points."),
    "sum-wordy::clarity": _dim(3, "One 78-word run-on sentence; hard to scan."),
    "sum-opinion-drift::__gate__": _gate(
        _fail("'Frankly this is a long-overdue and welcome investment' is the writer's opinion.")
    ),
    "sum-opinion-drift::faithfulness": _per_run(
        _dim(
            4,
            "Facts match; the opinion sentence adds nothing unsupported.",
            "raises per-pupil spending by four\npercent",
        ),
        _dim(
            3,
            "The 'long-overdue' framing reads as an unsupported evaluative claim.",
            "raises per-pupil spending by four\npercent",
        ),
        _dim(
            4,
            "Core facts supported.",
            "funds a new after-school tutoring programme at all eight elementary\nschools",
        ),
        _dim(2, "Editorial claim treated as an unsupported assertion about the budget.", ""),
        _dim(4, "Facts supported.", "raises per-pupil spending by four\npercent"),
    ),
    "sum-opinion-drift::completeness": _dim(5, "Both required points covered."),
    "sum-opinion-drift::clarity": _per_run(
        _dim(4, "Readable."),
        _dim(4, "Readable."),
        _dim(3, "The opinion sentence interrupts the flow."),
        _dim(4, "Readable."),
        _dim(4, "Readable."),
    ),
    "sum-noref::__gate__": _gate(_pass("Neutral tone.")),
    "sum-noref::clarity": _dim(3, "Understandable; slightly list-like."),
    # faithfulness + completeness are NOT_EVALUATED (no reference / no points) — no key needed.
    # ---- support email ----
    "se-strong::__gate__": _gate(
        _pass("Names the cracked jug explicitly."),
        _pass("States the replacement ships within 3 business days and it is approved."),
    ),
    "se-strong::faithfulness": _dim(
        5,
        "Every policy statement matches the policy.",
        "Defective items reported within 30 days are\nreplaced at no cost",
    ),
    "se-strong::clarity": _dim(5, "Short, warm, actionable."),
    "se-overpromise::__gate__": _gate(
        _pass("Acknowledges the kettle failure."),
        _pass("Says the refund happens today."),
    ),
    "se-overpromise::faithfulness": _per_run(
        _dim(
            1,
            "The policy says cash or card refunds are not offered; the reply promises one.",
            "Cash or card refunds are not offered",
        ),
        _dim(2, "Contradicts the no-refund policy.", "Cash or card refunds are not offered"),
        _dim(1, "Directly contradicts the policy.", "Cash or card refunds are not offered"),
        _dim(2, "Contradicts the policy.", "Cash or card refunds are not offered"),
        _dim(1, "Contradicts the policy.", "Cash or card refunds are not offered"),
    ),
    "se-overpromise::clarity": _dim(4, "Clear enough, if wrong."),
    "se-retry::__gate__": _gate(
        _pass("Acknowledges the return request."),
        _pass("Offers to send a prepaid label as the next step."),
    ),
    "se-retry::faithfulness": {
        "per_run": [
            {
                "per_attempt": [
                    {"raw": "I think this is roughly a 4 out of 5 but let me think about it more"},
                    _dim(
                        5,
                        "Matches the 14-day store-credit policy exactly.",
                        "items may be returned within 14 days of\ndelivery for store credit",
                    ),
                ]
            }
        ]
        * 5
    },
    "se-retry::clarity": _dim(5, "Concise and clear."),
    "se-judgefail::__gate__": _gate(
        _pass("Acknowledges the defective grinder."),
        _pass("States the replacement ships within 3 business days."),
    ),
    "se-judgefail::faithfulness": {"per_run": [{"error": "provider unavailable"}] * 5},
    "se-judgefail::clarity": _dim(5, "Clear and correct."),
    # ---- grounded QA ----
    "gqa-strong::__gate__": _gate(_pass("Answers the warehouse question directly.")),
    "gqa-strong::faithfulness": _dim(
        5,
        "Exactly what the context states.",
        "The Marlow site is the\nonly one with automated cold storage",
    ),
    "gqa-strong::completeness": _dim(5, "Single-part question fully answered."),
    "gqa-strong::relevance": _dim(5, "On point."),
    "gqa-unstable::__gate__": _gate(_pass("Answers both parts of the question.")),
    "gqa-unstable::faithfulness": _per_run(
        _dim(5, "Both figures are in the context.", "ran 1,240 crossings in 2026"),
        _dim(
            3,
            "Crossing count is exact; 'that January' is a slight paraphrase of the install date.",
            "ran 1,240 crossings in 2026",
        ),
        _dim(5, "Supported.", "a new scheduling system installed in January 2026"),
        _dim(2, "Marked down for the paraphrase of the install timing.", ""),
        _dim(5, "Supported.", "ran 1,240 crossings in 2026"),
    ),
    "gqa-unstable::completeness": _dim(5, "Both parts answered."),
    "gqa-unstable::relevance": _dim(4, "On topic."),
    "gqa-omission::__gate__": _gate(_pass("Addresses the fuel-spend part of the question.")),
    "gqa-omission::faithfulness": _dim(
        5, "The fuel-spend figure matches the context.", "cut fuel spend by 620,000 dollars"
    ),
    "gqa-omission::completeness": _per_run(
        _dim(2, "Answers the fuel-spend part; the electric last-mile share is missing."),
        _dim(2, "Only one of two parts answered."),
        _dim(2, "Misses the electric last-mile figure."),
        _dim(2, "Half the question is unanswered."),
        _dim(2, "Second part not addressed."),
    ),
    "gqa-omission::relevance": _dim(5, "On topic, just incomplete."),
    "gqa-hallucinated::__gate__": _gate(
        _pass("It does give a revenue figure in response to the question.")
    ),
    "gqa-hallucinated::faithfulness": _per_run(
        _dim(4, "Reads as well-supported.", "annual revenue for 2026 was 4.2 million dollars"),
        _dim(4, "Looks supported.", "annual revenue for 2026 was 4.2 million dollars"),
        _dim(3, "Mostly fine.", "reported approximately 4.2 million dollars in annual revenue"),
        _dim(4, "Supported.", "annual revenue for 2026 was 4.2 million dollars"),
        _dim(4, "Supported.", "annual revenue for 2026 was 4.2 million dollars"),
    ),
    "gqa-hallucinated::completeness": _dim(
        1, "Does not acknowledge that the context withholds the revenue figure."
    ),
    "gqa-hallucinated::relevance": _dim(3, "On topic but fabricated."),
}

# --------------------------------------------------------------------------- #
# Write + self-check
# --------------------------------------------------------------------------- #


def _write_jsonl(name: str, rows: list[dict]) -> None:
    path = DATASETS / name
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=True) for r in rows) + "\n", encoding="utf-8"
    )


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _sentences(text: str) -> int:
    n = len(re.findall(r"[.!?]+(?=\s|$)", text.strip()))
    return n if n or not text.strip() else 1


def _check() -> None:
    all_items = {r["id"]: r for r in (*SUMMARIZATION, *SUPPORT_EMAIL, *GROUNDED_QA)}

    # deterministic outcomes the scenarios rely on
    assert _words(all_items["sum-strong"]["candidate_response"]) <= 60
    assert _sentences(all_items["sum-strong"]["candidate_response"]) <= 3
    assert _words(all_items["sum-wordy"]["candidate_response"]) > 60, (
        "sum-wordy must break the 60-word rule"
    )
    assert _words(all_items["sum-opinion-drift"]["candidate_response"]) <= 60
    assert _sentences(all_items["sum-opinion-drift"]["candidate_response"]) <= 3
    assert _words(all_items["sum-noref"]["candidate_response"]) <= 60

    ticket_re = re.compile(r"#\d{4,}")
    overpromise_re = re.compile(
        r"(?i)\b(full refund|100% refund|guarantee(d)?|refund you|refund to your card)\b"
    )
    for sid in ("se-strong", "se-overpromise", "se-retry", "se-judgefail"):
        assert ticket_re.search(all_items[sid]["candidate_response"]), f"{sid} missing ticket #"
    assert overpromise_re.search(all_items["se-overpromise"]["candidate_response"]), (
        "se-overpromise must trip the policy_safety rule"
    )
    for sid in ("se-strong", "se-retry", "se-judgefail"):
        assert not overpromise_re.search(all_items[sid]["candidate_response"]), (
            f"{sid} must NOT trip the policy_safety rule"
        )

    for gid in ("gqa-strong", "gqa-unstable", "gqa-omission", "gqa-hallucinated"):
        assert _sentences(all_items[gid]["candidate_response"]) <= 3

    # every "verified" evidence quote must be a real substring of its reference
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().lower()

    verified_expectations = {
        "sum-strong::faithfulness",
        "sum-wordy::faithfulness",
        "se-strong::faithfulness",
        "se-overpromise::faithfulness",
        "se-retry::faithfulness",
        "gqa-strong::faithfulness",
        "gqa-omission::faithfulness",
    }
    for key in verified_expectations:
        item_id = key.split("::")[0]
        ref = _norm(all_items[item_id]["reference"])
        entry = MOCK[key]
        variants = entry.get("per_run", [entry])
        for v in variants:
            v = v.get("per_attempt", [v])[-1] if isinstance(v, dict) and "per_attempt" in v else v
            q = v.get("evidence_quote", "")
            if q:
                assert _norm(q) in ref, f"{key}: quote not in reference: {q!r}"

    # the hallucinated quote must NOT be in its context
    hq = MOCK["gqa-hallucinated::faithfulness"]["per_run"][0]["evidence_quote"]
    assert _norm(hq) not in _norm(all_items["gqa-hallucinated"]["reference"]), (
        "gqa-hallucinated quote should be absent from the context"
    )


def main() -> None:
    DATASETS.mkdir(exist_ok=True)
    _write_jsonl("summarization.jsonl", SUMMARIZATION)
    _write_jsonl("support_email.jsonl", SUPPORT_EMAIL)
    _write_jsonl("grounded_qa.jsonl", GROUNDED_QA)
    (DATASETS / "_mock_judgments.json").write_text(
        json.dumps(MOCK, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    _check()
    print("wrote 3 datasets + _mock_judgments.json; self-checks passed")


if __name__ == "__main__":
    main()
