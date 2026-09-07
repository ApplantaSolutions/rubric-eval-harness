# Security notes

## Credential handling

- The only credential this project uses is `ANTHROPIC_API_KEY`, read from the
  environment (or a git-ignored `.env`) by `rubric_eval.providers.anthropic`
  when — and only when — you run with `--provider anthropic`.
- The key is never logged, printed, included in an error message, or written to
  a report. Reports record the model *name* and parameters only.
- `.env` and `.env.*` are git-ignored; `.env.example` contains blank
  placeholders and is the only env file tracked.
- The default demo (`--provider mock`) needs no key and makes no network
  request.

## `scripts/scan_secrets.py`

A lightweight, self-contained regex scanner. It is run locally (`make
secret-scan`) and in CI.

**What it does:** scans tracked-style text files (Python, Markdown, YAML, JSON,
TOML, HTML, shell, `.env`) for a set of well-known secret shapes — Anthropic
(`sk-ant-…`), OpenAI (`sk-…`), AWS access keys (`AKIA…`), Google API keys
(`AIza…`), Stripe live keys, Slack tokens, GitHub PATs, PEM private-key blocks,
and generic `api_key`/`secret`/`password`/`token = "…"` assignments. It skips
`.git`, `.venv`, caches, `out/`, and `node_modules`, and allowlists
`.env.example`. It exits non-zero on any match.

**What it does NOT guarantee:**

- It does **not** prove the repository is free of secrets in all possible forms.
  It matches known patterns only. A credential in an unusual format, split across
  lines, base64-wrapped, or in a binary file will not be caught.
- It does **not** scan git history — only the working tree.
- It is **not** a replacement for a dedicated tool.

## Recommended before making the repository public

- Run a full-history scan with a dedicated tool
  ([`gitleaks`](https://github.com/gitleaks/gitleaks) or
  [`detect-secrets`](https://github.com/Yelp/detect-secrets)).
- A `detect-secrets` baseline (`.secrets.baseline`) + a pre-commit hook is a
  reasonable future enhancement. **It is not currently implemented** — this repo
  relies on the regex scanner above plus manual review.
- Confirm no `.env` file is present (`.gitignore` covers it, but verify).

## Reporting

This is a portfolio project. If you find a security issue in the code, open an
issue (once the repository is public) — there is no private disclosure channel.
