"""MockProvider: deterministic, offline."""

from __future__ import annotations

import json

import pytest

from rubric_eval.providers.base import Provider
from rubric_eval.providers.mock import MockProvider

_USER_TMPL = "EVAL_KEY: {key}\nRUN_INDEX: {run}\n<prompt body>"


def test_satisfies_provider_protocol():
    assert isinstance(MockProvider(), Provider)


def test_known_key_returns_configured_judgment():
    p = MockProvider(
        {"item-1::faithfulness": {"score": 2, "rationale": "unsupported", "evidence_quote": "x"}}
    )
    out = p.complete(
        system="s", user=_USER_TMPL.format(key="item-1::faithfulness", run=0), temperature=0.0
    )
    parsed = json.loads(out)
    assert parsed["score"] == 2
    assert parsed["rationale"] == "unsupported"


def test_deterministic_same_input_same_output():
    p = MockProvider({"k::d": {"score": 4, "rationale": "r", "evidence_quote": ""}})
    user = _USER_TMPL.format(key="k::d", run=0)
    a = p.complete(system="s", user=user, temperature=0.0)
    b = p.complete(system="s", user=user, temperature=0.0)
    assert a == b


def test_per_run_variation_by_run_index():
    p = MockProvider(
        {
            "k::clarity": {
                "per_run": [
                    {"score": 4, "rationale": "r", "evidence_quote": ""},
                    {"score": 2, "rationale": "r", "evidence_quote": ""},
                    {"score": 4, "rationale": "r", "evidence_quote": ""},
                ]
            }
        }
    )
    scores = [
        json.loads(
            p.complete(system="s", user=_USER_TMPL.format(key="k::clarity", run=i), temperature=0.0)
        )["score"]
        for i in range(3)
    ]
    assert scores == [4, 2, 4]


def test_unknown_key_falls_back_deterministically_without_error():
    p = MockProvider()
    user = _USER_TMPL.format(key="never::seen", run=0)
    out1 = p.complete(system="s", user=user, temperature=0.0)
    out2 = p.complete(system="s", user=user, temperature=0.0)
    assert out1 == out2
    parsed = json.loads(out1)
    assert 2 <= parsed["score"] <= 5
    assert "mock fallback" in parsed["rationale"]


def test_no_marker_still_returns_valid_json():
    p = MockProvider()
    out = p.complete(system="s", user="a prompt with no markers", temperature=0.0)
    json.loads(out)  # must not raise


def test_from_file(tmp_path):
    f = tmp_path / "j.json"
    f.write_text(
        json.dumps({"a::b": {"score": 3, "rationale": "r", "evidence_quote": ""}}), encoding="utf-8"
    )
    p = MockProvider.from_file(f)
    out = json.loads(
        p.complete(system="s", user=_USER_TMPL.format(key="a::b", run=0), temperature=0.0)
    )
    assert out["score"] == 3


def test_mock_provider_imports_no_network_library():
    import rubric_eval.providers.mock as mod

    # The mock module must not pull in the anthropic SDK or an HTTP client.
    text = open(mod.__file__, encoding="utf-8").read()
    assert "import anthropic" not in text
    assert "import requests" not in text
    assert "urllib" not in text


# --------------------------------------------------------------------------- #
# Checkpoint 3 additions: metadata routing, per_attempt, error, raw
# --------------------------------------------------------------------------- #


def _meta(key, run=0, attempt=1):
    return {"eval_key": key, "run_index": run, "attempt": attempt}


def test_metadata_routing_preferred_over_prompt_markers():
    p = MockProvider({"x::d": {"score": 5, "rationale": "r", "evidence_quote": ""}})
    out = json.loads(
        p.complete(system="s", user="no markers here", temperature=0.0, metadata=_meta("x::d"))
    )
    assert out["score"] == 5


def test_error_entry_raises_provider_error():
    from rubric_eval.errors import ProviderError

    p = MockProvider({"x::d": {"error": "rate limited"}})
    with pytest.raises(ProviderError, match="rate limited"):
        p.complete(system="s", user="", temperature=0.0, metadata=_meta("x::d"))


def test_raw_entry_returned_verbatim():
    p = MockProvider({"x::d": {"raw": "this is not json"}})
    assert (
        p.complete(system="s", user="", temperature=0.0, metadata=_meta("x::d"))
        == "this is not json"
    )


def test_per_attempt_varies_by_attempt():
    p = MockProvider(
        {
            "x::d": {
                "per_attempt": [
                    {"raw": "broken"},
                    {"score": 4, "rationale": "r", "evidence_quote": ""},
                ]
            }
        }
    )
    a1 = p.complete(system="s", user="", temperature=0.0, metadata=_meta("x::d", attempt=1))
    a2 = p.complete(system="s", user="", temperature=0.0, metadata=_meta("x::d", attempt=2))
    assert a1 == "broken"
    assert json.loads(a2)["score"] == 4


def test_nested_per_run_then_per_attempt():
    p = MockProvider(
        {
            "x::d": {
                "per_run": [
                    {"score": 5, "rationale": "r", "evidence_quote": ""},
                    {
                        "per_attempt": [
                            {"raw": "junk"},
                            {"score": 2, "rationale": "r", "evidence_quote": ""},
                        ]
                    },
                ]
            }
        }
    )
    r0 = json.loads(p.complete(system="s", user="", temperature=0.0, metadata=_meta("x::d", run=0)))
    r1a1 = p.complete(
        system="s", user="", temperature=0.0, metadata=_meta("x::d", run=1, attempt=1)
    )
    r1a2 = json.loads(
        p.complete(system="s", user="", temperature=0.0, metadata=_meta("x::d", run=1, attempt=2))
    )
    assert r0["score"] == 5
    assert r1a1 == "junk"
    assert r1a2["score"] == 2
