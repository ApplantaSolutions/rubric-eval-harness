# Methodology

How the harness turns a rubric + a response into a verdict, and what each number
does and does not mean. The generated report repeats the key limitations inline;
this is the longer version.

## Dimension types

| Type | How it is scored | Needs |
|---|---|---|
| `gate` | Instruction-following checklist. Each instruction is `pass` / `fail` — deterministically when a rule is attached, otherwise by the judge. | — |
| `deterministic` | Code rules only (word/sentence/char counts, required/forbidden substrings, regex, valid-JSON). 100% repeatable. | — |
| `reference_grounded` | Judge scores 1–N against the rubric anchors, **only** against the supplied reference, and must quote a supporting span. | a `reference` |
| `spec_grounded` | Judge scores 1–N against the anchors and a `required_points` list (or the reference). | `required_points` **or** a `reference` |
| `judged` | Judge scores 1–N against the anchors. No evidence requirement. | — |

If a judged dimension's evidence requirement is not met, it is **NOT_EVALUATED**:
excluded from the mean and the verdict, and never scored zero.

## The verdict engine

Deterministic, ordered, no expression evaluation:

1. Instruction-following gate `FAIL` → **Fail**.
2. A configured safety dimension failed → **Fail** or a cap at **Needs work**
   (`rubric.verdict.safety_failure_verdict`).
3. Anything still unresolved (a judged dimension awaiting the judge, or the gate
   pending / errored) → **Unresolved**.
4. Otherwise: `cap = Needs work` if any deterministic check failed or any judged
   dimension mean is below `needs_work_floor_any`; `base` = Excellent / Acceptable
   / Needs work from the mean of the evaluated judged means; **verdict = min(base,
   cap)**.

The `indicative_score` is the unweighted mean of the evaluated judged means. It
is labelled "indicative" everywhere — it is not the verdict and not a calibrated
metric.

## N-run judging and consistency

Every judged dimension is scored `N` times (default 5). **Every run is kept.**
The harness reports the raw scores, the mean, the **population** standard
deviation, min/max, and the pairwise disagreement rate (fraction of score pairs
differing by ≥ `disagreement_threshold`).

The reliability **label** — STABLE / SOME_VARIANCE / UNRELIABLE — is derived from
`ReliabilityConfig` thresholds. **Those thresholds are configurable operational
heuristics, not statistically validated boundaries.** They help flag unstable
judge behaviour; they do not establish statistical ground truth. The raw numbers
travel with every label and are the source of truth.

Repeated judging measures **judge-output consistency under this configuration**
(model, temperature, prompt, run count). It is not a formal confidence interval.

## Instruction judging runs once

Instruction-following is judged a single time per item; judged rubric dimensions
receive `N` runs. **Verdict stability** re-computes the verdict from each single
judged run, so per-run variation reflects only the judged-dimension scores. A run
in which any evaluable judged dimension hit a judge error counts as "Unresolved"
for that run. Ties for the modal verdict resolve to the more conservative verdict
(`Unresolved` < `Fail` < `Needs work` < `Acceptable` < `Excellent`).

## Evidence verification

When the judge returns an `evidence_quote` for a reference-grounded dimension,
the harness checks **deterministically** whether that span actually occurs in the
supplied reference (exact, or after normalising whitespace / quote characters /
surrounding punctuation).

* This only verifies that **the quote exists**. It does **not** independently
  prove the underlying claim is true.
* If the quote is **not** in the reference, it is surfaced as **UNVERIFIED and
  possibly fabricated by the judge**. The judge's score is still shown as
  returned — the harness does not silently zero it or hide the condition. The
  evaluator itself can hallucinate evidence, and this makes that visible.

## Judge output contract and failures

The judge must return a single JSON object. The parser tolerates ```` ```json ````
fences and limited surrounding prose but rejects missing fields, wrong types,
non-numeric scores, and scores outside the rubric scale. On a malformed response
there is **one** corrective retry; if that also fails the run is recorded as a
judge error and the pipeline continues. If **every** run for a dimension fails,
the dimension is NOT_EVALUATED — no mean is invented.

## What this is not

* Not a model benchmark. It evaluates supplied responses against an explicit
  rubric and reports how it did so. There is no leaderboard.
* Not a claim that the judge model is correct. An LLM judge can be biased,
  inconsistent, or simply wrong.
* The dataset shipped with this project is entirely synthetic (see
  `datasets/README.md`).
