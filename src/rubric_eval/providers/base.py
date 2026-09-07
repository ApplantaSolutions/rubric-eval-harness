"""Judge provider interface.

A provider takes a system + user prompt and returns text. The judged-evaluation
pipeline is written entirely against this protocol so it can run offline against
:class:`~rubric_eval.providers.mock.MockProvider`.

``metadata`` carries harness bookkeeping (which item / dimension / run / attempt
this call is for). Real providers ignore it; the mock provider uses it to return
deterministic canned judgments. It is never part of the prompt sent to a model.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

DEFAULT_MAX_TOKENS = 1024


@runtime_checkable
class Provider(Protocol):
    name: str

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        metadata: dict | None = None,
    ) -> str:
        """Return the model's text response. Raises ProviderError on failure."""
        ...
