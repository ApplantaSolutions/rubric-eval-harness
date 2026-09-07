# Demo datasets

**Everything in this folder is synthetic.** The organisations, people, facts,
policies, emails, questions, and candidate responses were all invented for this
project. Nothing is derived from real user data, a real company, an employer, an
evaluation platform, a client, or any other project.

## What these datasets are for

They exist to **demonstrate how the harness behaves**, not to benchmark model
quality. Each item is written to exercise a specific evaluator behaviour:

| File | Rubric | Items |
|---|---|---|
| `summarization.jsonl` | `rubrics/summarization_quality.yaml` | 4 |
| `support_email.jsonl` | `rubrics/support_email_reply.yaml` | 4 |
| `grounded_qa.jsonl` | `rubrics/grounded_qa.yaml` | 4 |

Scenario coverage across the 12 items:

| Scenario | Item(s) |
|---|---|
| Strong response → Excellent | `sum-strong`, `se-strong`, `gqa-strong` |
| Weak response | `se-overpromise`, `gqa-omission`, `gqa-hallucinated` |
| Deterministic instruction failure | `sum-wordy` (exceeds the 60-word rule) |
| Judged instruction failure | `sum-opinion-drift` (editorialising) |
| Missing required evidence → NOT_EVALUATED | `sum-noref` (no reference / no required points) |
| Judge disagreement / reliability variance | `sum-opinion-drift` (some variance), `gqa-unstable` (unreliable) |
| Malformed judge output + successful retry | `se-retry` |
| Judge failure (all runs error) → NOT_EVALUATED, not zeroed | `se-judgefail` |
| Hallucinated / unverified judge evidence | `gqa-hallucinated` |
| Verdict instability across runs | `gqa-unstable` |

## Determinism

`_mock_judgments.json` is the offline judge fixture keyed by
`"<item_id>::<dimension_id>"` (or `"<item_id>::__gate__"`). With it, the entire
demo runs deterministically and with no API key:

```
rubric-eval run --rubric rubrics/grounded_qa.yaml \
                --dataset datasets/grounded_qa.jsonl \
                --provider mock --mock-judgments datasets/_mock_judgments.json \
                --out out/grounded_qa
```

## Regenerating

`python scripts/build_demo.py` rewrites all four files and self-checks that the
authored responses actually produce the intended deterministic outcomes (word
and sentence counts, regex matches) and that every "verified" evidence quote is
a real substring of its reference.
