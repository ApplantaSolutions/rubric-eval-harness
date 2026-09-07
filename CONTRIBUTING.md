# Contributing

This is a portfolio project, but contributions and forks are welcome. A few
non-negotiable rules:

## Data

- **Committed examples, datasets, and test fixtures must be synthetic / invented.**
  No real customer, employer, client, or evaluation-platform data — no real
  prompts, rubrics, responses, policies, names, or scenarios. If you need
  realistic-looking data, invent an organisation and a scenario. The existing
  `datasets/` and `tests/` follow this rule; keep it.
- No personal data of real people.

## Secrets

- **Never commit a real credential.** Keys come from the environment or a
  git-ignored `.env` only. `.env.example` holds blank placeholders.
- Run `python scripts/scan_secrets.py` before opening a PR. CI runs it too.

## Behavioural changes

- **Any change to evaluation behaviour needs a test.** The suite is offline
  (`pytest`, no API key, no network) and fast; add to it.
- If you change the engine or the report template, regenerate the committed
  examples: `python scripts/build_demo.py && python scripts/build_examples.py`.
  `tests/test_report.py` byte-compares them.

## Preserve transparent failure states

The whole point of this harness is that it does **not** hide evaluator problems.
Do not "fix" a test by:

- silently converting an unverified/hallucinated judge evidence quote into a
  verified one, or zeroing the score instead of flagging it;
- turning a `NOT_EVALUATED` dimension into a `0`;
- folding judge errors, gate errors, or unstable verdicts out of the aggregate
  metrics;
- weakening a reliability threshold just to make a label say `STABLE`.

If a genuine behaviour change is intended, document *why* in the PR and update
the methodology docs.

## Before you push

```bash
make lint          # ruff check
make format-check  # ruff format --check
make test          # pytest
make secret-scan   # scripts/scan_secrets.py
make demo          # regenerate + verify the synthetic demo reproduces
```

All five must be clean.
