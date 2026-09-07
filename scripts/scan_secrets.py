#!/usr/bin/env python3
"""Lightweight secret scanner for this repo.

Runs in CI and locally (``python scripts/scan_secrets.py``). It is a
belt-and-braces check, not a replacement for a dedicated tool — the README's
security section also recommends gitleaks for anyone forking this.

Exits non-zero if a likely secret is found in a tracked-style file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories never scanned.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "out",
    "dist",
    "build",
    "node_modules",
}

# Filenames allowed to contain key-shaped example text.
ALLOW_FILES = {".env.example"}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".cfg",
    ".ini",
    ".html",
    ".j2",
    ".sh",
    ".env",
    "",
}

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai key", re.compile(r"\bsk-[A-Za-z0-9]{40,}\b")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("stripe secret", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{16,}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("github pat", re.compile(r"\bghp_[0-9A-Za-z]{30,}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    (
        "generic bearer secret assignment",
        re.compile(
            r"(?i)(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][A-Za-z0-9+/_=-]{16,}['\"]"
        ),
    ),
]


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files.append(path)
    return files


def main() -> int:
    findings: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(ROOT).as_posix()
        if path.name in ALLOW_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(f"{rel}:{lineno}: possible {label}")

    if findings:
        print("POSSIBLE SECRETS FOUND:")
        for f in findings:
            print(f"  {f}")
        return 1

    print("scan_secrets: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
