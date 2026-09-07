"""Anthropic judge provider.

Configuration comes only from environment variables:

    ANTHROPIC_API_KEY   (required)
    EVAL_JUDGE_MODEL    (optional; defaults to DEFAULT_MODEL below)

The API key is never logged or included in any error message. Any SDK failure is
re-raised as the project's ``ProviderError``.
"""

from __future__ import annotations

import os

from ..errors import ProviderError
from .base import DEFAULT_MAX_TOKENS

# A model id that is valid at implementation time (2026-09). Override with
# EVAL_JUDGE_MODEL. See https://docs.anthropic.com/en/docs/about-claude/models
DEFAULT_MODEL = "claude-sonnet-4-5"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str, model: str) -> None:
        # Imported lazily so the package (and the whole test suite) does not
        # require the SDK to be importable in mock-only environments.
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError(
                "the 'anthropic' package is not installed; run: pip install anthropic"
            ) from exc

        self._model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    @classmethod
    def from_env(cls) -> AnthropicProvider:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Set it in your environment or a "
                "git-ignored .env file (see .env.example), or use --provider mock."
            )
        model = os.environ.get("EVAL_JUDGE_MODEL", "").strip() or DEFAULT_MODEL
        return cls(api_key=api_key, model=model)

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        metadata: dict | None = None,  # ignored; harness bookkeeping only
    ) -> str:
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 - normalise every SDK failure
            raise ProviderError(f"Anthropic request failed: {type(exc).__name__}: {exc}") from exc

        parts = [block.text for block in message.content if getattr(block, "type", None) == "text"]
        text = "".join(parts).strip()
        if not text:
            raise ProviderError("Anthropic returned an empty response")
        return text
