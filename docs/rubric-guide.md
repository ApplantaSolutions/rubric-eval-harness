# Rubric authoring guide

A rubric is a single YAML file describing **how to evaluate** a response. It is
loaded and strictly validated by `rubric_eval.rubric.load_rubric`; unknown keys
and contradictory configuration are rejected with a message that names the
offending field.

Validate a rubric without running anything:

```bash
rubric-eval validate --rubric rubrics/my_rubric.yaml
```

---

## Minimal worked rubric

```yaml
id: my_rubric
title: "My rubric"
scale: { min: 1, max: 5 }

dimensions:
  - id: instruction_following
    type: gate
    global_checks:
      - text: "Uses at most 60 words"
        method: deterministic
        rule: { name: max_words, kind: max_word_count, value: 60 }

  - id: clarity
    type: judged
    anchors:
      5: "Unambiguous and well ordered."
      3: "Understandable but awkward."
      1: "Hard to follow."
```

That is enough to run. Every other field has a sensible default.

---

## Top-level fields

| Field | Required | Default | Notes |
|---|---|---|---|
| `id` | yes | — | short identifier |
| `title` | yes | — | human title, shown in the report header |
| `version` | no | `1` | integer |
| `description` | no | `""` | free text |
| `scale` | yes | — | `{ min: <int>, max: <int> }`; `max - min` must be ≥ 2 |
| `dimensions` | yes | — | list; at least one; **at most one `gate`** |
| `verdict` | no | see below | thresholds and safety gates |
| `reliability` | no | see below | N-run heuristics |

---

## Dimensions

Every dimension has an `id`, a `type`, and an optional `description`. The rest
depends on the type.

### `type: gate` — instruction-following

The one pass/fail gate for the item. At most one gate per rubric.

| Field | Default | Notes |
|---|---|---|
| `global_checks` | `[]` | rubric-level instructions applied to every item |
| `include_item_instructions` | `true` | also check each dataset item's own `instructions` list |

Each `global_checks` entry:

```yaml
- text: "Human-readable instruction"
  method: deterministic          # or: judge
  rule: { name: ..., kind: ..., value: ... }   # required iff method == deterministic
```

- `method: deterministic` runs a rule (see **Rule kinds** below) — 100%
  repeatable.
- `method: judge` is resolved once per item by the LLM judge (pass/fail +
  rationale + an optional quote from the response).

**Gate outcome:** any deterministic `fail` → gate `FAIL` (never rescued by a
judged pass); else any judged instruction that could not be evaluated →
`ERROR`; else any still-pending → `PENDING`; else `PASS`. A gate `FAIL` makes
the item verdict `Fail`; `ERROR`/`PENDING` make it `Unresolved`.

### `type: deterministic` — code checks only

```yaml
- id: format
  type: deterministic
  rules:
    - { name: no_headings, kind: forbidden_regex, pattern: '(?m)^\s*#' }
    - { name: max_len, kind: max_chars, value: 800 }
```

- `rules` — at least one. All must pass for the dimension to pass.
- A `deterministic` dimension named in `verdict.safety_dimension_ids` acts as a
  **safety gate** (see Verdict).

### `type: judged` — subjective quality, no evidence

```yaml
- id: clarity
  type: judged
  anchors:
    5: "Unambiguous and well ordered."
    3: "Understandable but awkward."
    1: "Hard to follow."
```

- `anchors` — required; a map from integer score to a description. Keys must be
  within `scale`, and **both scale endpoints must be present** (e.g. `1` and `5`
  for a 1–5 scale). Intermediate anchors are recommended but optional.
- No `reference` or `required_points` is used. Scored `N` times.

### `type: reference_grounded` — faithfulness to a source

```yaml
- id: faithfulness
  type: reference_grounded
  anchors:
    5: "Every claim is supported by the reference."
    3: "Mostly supported; one minor detail is not."
    1: "Contradicts the reference or is largely unsupported."
```

- The dataset item **must** supply a non-empty `reference`. If it doesn't, this
  dimension is `NOT_EVALUATED` for that item (excluded from the verdict, never
  zeroed).
- The judge is instructed to score **only against the supplied reference** — no
  outside knowledge — and to return a **verbatim** supporting or contradicting
  quote from it.
- The harness then **verifies that quote deterministically**: exact substring,
  or a match after normalising whitespace / quote characters / surrounding
  punctuation. A quote that is not found is reported as **UNVERIFIED — possible
  judge hallucination**. The judge's score is kept as returned; the harness does
  not zero it or hide the condition.
- `requires` defaults to `reference`; you may set it to `reference_or_points`.

### `type: spec_grounded` — coverage of required points

```yaml
- id: completeness
  type: spec_grounded
  anchors:
    5: "Covers every required point."
    3: "Covers the main point but misses a secondary one."
    1: "Misses the primary point."
```

- The dataset item must supply `required_points` (a list) **or** a `reference`.
  If it supplies neither, this dimension is `NOT_EVALUATED`.
- `requires` defaults to `reference_or_points`; you may set it to
  `required_points`.

---

## Rule kinds (deterministic)

Used in a `deterministic` dimension's `rules` or a gate's deterministic
`global_checks`.

| `kind` | Takes | Passes when |
|---|---|---|
| `max_word_count` | `value: <int>` | whitespace-token count ≤ value |
| `min_word_count` | `value: <int>` | count ≥ value |
| `max_sentences` | `value: <int>` | heuristic sentence count ≤ value |
| `min_sentences` | `value: <int>` | count ≥ value |
| `max_chars` | `value: <int>` | `len(response)` ≤ value |
| `min_chars` | `value: <int>` | `len(response)` ≥ value |
| `required_substring` | `value: <str>` | substring is present |
| `forbidden_substring` | `value: <str>` | substring is absent |
| `required_regex` | `pattern: <str>` | `re.search` matches |
| `forbidden_regex` | `pattern: <str>` | `re.search` does not match |
| `valid_json` | — | `json.loads(response)` succeeds |

Every rule also takes `name` (required, shown in the report) and
`case_sensitive` (default `true`; applies to substring and regex kinds).

> Sentence counting is a heuristic: groups of terminal punctuation (`.` `!` `?`)
> followed by whitespace or end-of-string. Non-empty text with no terminal
> punctuation counts as one sentence. Abbreviation-heavy text can miscount.

---

## `verdict:` block

```yaml
verdict:
  excellent_min_mean: 4.0      # mean of judged means ≥ this → Excellent
  acceptable_min_mean: 3.0     # ≥ this → Acceptable
  needs_work_floor_any: 2.5    # ANY judged dimension mean below this caps the verdict at Needs work
  safety_dimension_ids: []     # deterministic dimension ids that act as safety gates
  safety_failure_verdict: needs_work   # or: fail
```

Verdict order (worst → best): `Fail` < `Needs work` < `Acceptable` <
`Excellent`. Separately, `Unresolved` when a judged dimension or the gate has
not been evaluated.

Rules, in order:

1. Gate `FAIL` → **Fail**.
2. A `safety_dimension_ids` deterministic dimension failed → **Fail** (if
   `safety_failure_verdict: fail`) or a cap at **Needs work**.
3. A judged dimension still pending, or the gate pending/errored → **Unresolved**.
4. Otherwise: `cap = Needs work` if any deterministic check failed or any judged
   mean is below `needs_work_floor_any`; `base` from the mean of evaluated
   judged means vs. the thresholds; **verdict = min(base, cap)**.

`NOT_EVALUATED` dimensions are excluded from the mean and never scored zero.

---

## `reliability:` block

```yaml
reliability:
  runs_default: 5              # N judge runs per judged dimension (CLI --runs overrides)
  disagreement_threshold: 2    # a score pair differing by ≥ this counts as a "disagreement"
  low_variance_stdev: 0.5      # ≤ this and no disagreement → STABLE
  high_variance_stdev: 1.0     # > this → UNRELIABLE
  unreliable_disagreement_rate: 0.34   # disagreement rate > this → UNRELIABLE
  stable_agree_fraction: 0.8   # reserved for verdict-stability reporting
```

**These thresholds are configurable operational heuristics, not statistically
validated boundaries.** The label (`STABLE` / `SOME_VARIANCE` / `UNRELIABLE` /
`NOT_APPLICABLE`) is a reading aid; the raw per-run scores, mean, population
stdev, min/max, and pairwise disagreement rate are reported alongside it and are
the source of truth.

---

## How a dimension becomes `NOT_EVALUATED`

- `reference_grounded` (or `spec_grounded` with `requires: reference`) and the
  item has no `reference`.
- `spec_grounded` and the item has neither `required_points` nor a `reference`.
- **Every** judge run for the dimension failed (provider error, or malformed
  output after the one corrective retry).

In all cases the dimension is excluded from the mean and the verdict, the reason
is recorded, and the item is listed in the report's failures-first section. It
is **never** scored zero.

---

## Common authoring mistakes

| Mistake | What happens |
|---|---|
| Judged dimension without `anchors` | rejected at load: *"requires 'anchors'"* |
| `anchors` missing a scale endpoint (e.g. only `3` and `5` on a 1–5 scale) | rejected: *"anchors must include both scale endpoints"* |
| Two `gate` dimensions | rejected: *"at most one 'gate' dimension"* |
| `safety_dimension_ids` naming a judged (not deterministic) dimension | rejected: *"not a 'deterministic' dimension"* |
| `scale: { min: 1, max: 2 }` | rejected: *"range too small"* |
| Deterministic `rule` with `kind: max_word_count` and a string `value` | rejected: *"requires an integer 'value'"* |
| `reference_grounded` dimension but the dataset items have no `reference` | loads fine, but every item's dimension is `NOT_EVALUATED` |
| Expecting per-item `instructions` to be checked with `include_item_instructions: false` | they are ignored |
