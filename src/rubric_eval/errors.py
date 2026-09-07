"""Typed errors. Callers (CLI, tests) can catch these to produce clean output."""

from __future__ import annotations


class RubricEvalError(Exception):
    """Base class for every error this package raises deliberately."""


class RubricError(RubricEvalError):
    """A rubric file is missing, malformed, or internally invalid."""


class DatasetError(RubricEvalError):
    """A dataset file is missing, malformed, empty, or contains an invalid item."""


class ProviderError(RubricEvalError):
    """A judge provider could not be constructed or a call failed."""


class ConfigError(RubricEvalError):
    """Run configuration is invalid (e.g. missing API key for the chosen provider)."""


class JudgeParseError(RubricEvalError):
    """A judge model returned output that could not be parsed into a valid
    judgment (bad JSON, missing field, wrong type, score out of range)."""
