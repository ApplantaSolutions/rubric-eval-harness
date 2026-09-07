"""Evidence verification + evidence-requirement resolution."""

from __future__ import annotations

from rubric_eval.checks.evidence import (
    resolve_evidence_requirement,
    verify_evidence,
)
from rubric_eval.dataset import EvalItem
from rubric_eval.models import Dimension

_REF = (
    "The Ferndale Study reports that response times fell by eighteen percent after "
    "the new dispatch process was introduced in March."
)


def _item(**kw) -> EvalItem:
    base = {"id": "i", "task": "t", "candidate_response": "r"}
    base.update(kw)
    return EvalItem(**base)


class TestVerifyEvidence:
    def test_exact_match(self):
        r = verify_evidence("response times fell by eighteen percent", _REF)
        assert r.verified is True
        assert r.method == "exact"

    def test_normalized_match_whitespace_and_quotes(self):
        quote = "  “response times fell   by eighteen percent”  "
        r = verify_evidence(quote, _REF)
        assert r.verified is True
        assert r.method == "normalized"

    def test_hallucinated_quote_not_found(self):
        r = verify_evidence("response times fell by ninety percent", _REF)
        assert r.verified is False
        assert r.method == "not_found"
        assert "fabricated" in r.note

    def test_evidence_without_reference(self):
        r = verify_evidence("something", None)
        assert r.verified is False
        assert r.method == "no_reference"

    def test_empty_quote(self):
        r = verify_evidence("   ", _REF)
        assert r.verified is False
        assert r.method == "empty"


class TestResolveRequirement:
    def _dim(self, **kw) -> Dimension:
        base = {"id": "d", "type": "judged", "anchors": {1: "a", 5: "b"}}
        base.update(kw)
        return Dimension(**base)

    def test_none_always_evaluable(self):
        d = self._dim()  # plain judged, requires == none
        assert resolve_evidence_requirement(d, _item()).can_evaluate is True

    def test_reference_required_present(self):
        d = self._dim(type="reference_grounded")
        avail = resolve_evidence_requirement(d, _item(reference=_REF))
        assert avail.can_evaluate is True

    def test_reference_required_absent_not_evaluated(self):
        d = self._dim(type="reference_grounded")
        avail = resolve_evidence_requirement(d, _item())
        assert avail.can_evaluate is False
        assert "requires a reference passage" in avail.reason

    def test_spec_grounded_with_points_only(self):
        d = self._dim(type="spec_grounded")
        avail = resolve_evidence_requirement(d, _item(required_points=["x"]))
        assert avail.can_evaluate is True

    def test_spec_grounded_with_neither_not_evaluated(self):
        d = self._dim(type="spec_grounded")
        avail = resolve_evidence_requirement(d, _item())
        assert avail.can_evaluate is False
        assert "neither" in avail.reason

    def test_required_points_only_requirement(self):
        d = self._dim(type="spec_grounded", requires="required_points")
        assert resolve_evidence_requirement(d, _item()).can_evaluate is False
        assert resolve_evidence_requirement(d, _item(required_points=["a"])).can_evaluate is True
