"""Deterministic offline judge provider.

Used for the test suite and for ``--provider mock`` (the offline demo). Imports
no network library and never makes a request.

It returns canned judgments from a ``judgments`` map keyed by ``eval_key``
(``"<item_id>::<dimension_id>"`` or ``"<item_id>::__gate__"``), supplied either
as a dict or via :meth:`from_file`. Resolution order for an entry:

    per_run[run_index]  ->  per_attempt[attempt-1]  ->  {"error": ...}  raises
                                                    ->  {"raw": "..."}  returned verbatim
                                                    ->  otherwise json.dumps(entry)

``per_run`` / ``per_attempt`` entries are resolved recursively, so you can nest
(e.g. run 3 is malformed-then-valid, run 4 raises a provider error).

Unknown keys fall back to a deterministic hash-derived judgment so the provider
never raises unexpectedly.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..errors import ProviderError
from .base import DEFAULT_MAX_TOKENS

_KEY_RE = re.compile(r"EVAL_KEY:\s*(\S+)")
_RUN_RE = re.compile(r"RUN_INDEX:\s*(\d+)")
_ATTEMPT_RE = re.compile(r"ATTEMPT:\s*(\d+)")


class MockProvider:
    name = "mock"

    def __init__(self, judgments: dict[str, Any] | None = None) -> None:
        self._judgments: dict[str, Any] = judgments or {}

    @classmethod
    def from_file(cls, path: str | Path) -> MockProvider:
        p = Path(path)
        if not p.is_file():
            raise ProviderError(f"mock judgments file not found: {p}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{p}: invalid mock judgments JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ProviderError(f"{p}: mock judgments file must contain a JSON object")
        return cls(data)

    # -- Provider protocol -------------------------------------------------- #

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        metadata: dict | None = None,
    ) -> str:
        key, run_index, attempt = self._resolve_context(user, metadata)

        if key is not None and key in self._judgments:
            return self._render(self._judgments[key], run_index, attempt)

        return json.dumps(self._fallback(key or user))

    # -- internals ------------------------------------------------------ #

    @staticmethod
    def _resolve_context(user: str, metadata: dict | None) -> tuple[str | None, int, int]:
        if metadata:
            key = metadata.get("eval_key")
            run_index = int(metadata.get("run_index", 0))
            attempt = int(metadata.get("attempt", 1))
            return key, run_index, attempt
        km = _KEY_RE.search(user)
        rm = _RUN_RE.search(user)
        am = _ATTEMPT_RE.search(user)
        return (
            km.group(1) if km else None,
            int(rm.group(1)) if rm else 0,
            int(am.group(1)) if am else 1,
        )

    def _render(self, entry: Any, run_index: int, attempt: int) -> str:
        entry = self._select(entry, run_index, attempt)
        if isinstance(entry, dict):
            if "error" in entry:
                raise ProviderError(str(entry["error"]))
            if "raw" in entry:
                return str(entry["raw"])
        return json.dumps(entry)

    def _select(self, entry: Any, run_index: int, attempt: int) -> Any:
        # Resolve per_run / per_attempt wrappers, possibly nested.
        for _ in range(8):  # generous ceiling; nesting is never deep in practice
            if not isinstance(entry, dict):
                return entry
            if "per_run" in entry:
                variants = entry["per_run"]
                entry = variants[run_index % len(variants)]
                continue
            if "per_attempt" in entry:
                variants = entry["per_attempt"]
                idx = min(attempt, len(variants)) - 1
                entry = variants[idx]
                continue
            return entry
        return entry

    @staticmethod
    def _fallback(seed: str) -> dict[str, Any]:
        digest = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
        score = 2 + (digest % 4)  # deterministic 2..5
        return {
            "score": score,
            "rationale": f"[mock fallback] deterministic placeholder judgment for {seed!r}.",
            "evidence_quote": "",
        }
