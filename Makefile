# Convenience targets. Run inside an activated virtualenv (or override PY).
#   Windows:  .venv\Scripts\activate   then  make test
#   Unix:     source .venv/bin/activate then  make test
# Every target also works as a plain command if you don't have `make`.

PY ?= python

.PHONY: help install test lint format format-check secret-scan validate demo all

help:
	@echo "install       pip install -e .[dev]"
	@echo "test          pytest (offline; no API key, no network)"
	@echo "lint          ruff check"
	@echo "format        ruff format (writes)"
	@echo "format-check  ruff format --check"
	@echo "secret-scan   scripts/scan_secrets.py"
	@echo "validate      load + validate every shipped rubric and dataset"
	@echo "demo          regenerate datasets + examples and verify they reproduce"
	@echo "all           lint + format-check + test + secret-scan + validate + demo"

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff format .

format-check:
	$(PY) -m ruff format --check .

secret-scan:
	$(PY) scripts/scan_secrets.py

validate:
	$(PY) -c "import pathlib, sys; from rubric_eval.rubric import load_rubric; from rubric_eval.dataset import load_dataset; \
pairs=[('rubrics/summarization_quality.yaml','datasets/summarization.jsonl'), \
('rubrics/support_email_reply.yaml','datasets/support_email.jsonl'), \
('rubrics/grounded_qa.yaml','datasets/grounded_qa.jsonl')]; \
[ (load_rubric(r), load_dataset(d), print(f'ok  {r}  +  {d}')) for r,d in pairs ]"

demo:
	$(PY) scripts/build_demo.py
	$(PY) scripts/build_examples.py
	$(PY) -m pytest tests/test_report.py -q

all: lint format-check test secret-scan validate demo
