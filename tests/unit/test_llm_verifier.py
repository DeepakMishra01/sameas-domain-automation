"""Unit tests for the LLM verifier and prompt (stubbed client, no network)."""

from typing import Any
from uuid import uuid4

from domain_resolver.classification.relationship_types import PartOfSubtype, RelationshipType
from domain_resolver.features.results import FeatureSet
from domain_resolver.llm.prompt import build_user_prompt
from domain_resolver.llm.verifier import LlmRelationshipVerifier
from domain_resolver.matching.views import DomainFeatureView


class _StubClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.model = "stub-model"

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        return self._response


class _BoomClient:
    model = "boom"

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        raise RuntimeError("connection refused")


def _view(host: str, **over: Any) -> DomainFeatureView:
    did = uuid4()
    f = FeatureSet(
        feature_version="v",
        domain_id=str(did),
        observation_id=str(uuid4()),
        normalized_domain=host,
        **over,
    )
    return DomainFeatureView(domain_id=did, observation_id=uuid4(), host=host, features=f)


def test_prompt_includes_both_domains_and_facts() -> None:
    a = _view("a.test", normalized_title="Acme Store", referenced_domains=["b.test"])
    b = _view("b.test", normalized_title="Acme HQ")
    prompt = build_user_prompt(a, b, "assumed part of b.test")
    assert "a.test" in prompt and "b.test" in prompt
    assert "acme store" in prompt.lower()
    assert "assumed part of" in prompt


def test_prompt_includes_web_evidence_when_provided() -> None:
    a = _view("a.test", normalized_title="Acme")
    b = _view("b.test", normalized_title="Beta")
    prompt = build_user_prompt(a, b, "", web_evidence="- News: Beta acquired Acme in 2021")
    assert "WEB SEARCH RESULTS" in prompt
    assert "Beta acquired Acme" in prompt


def test_verifier_parses_part_of_verdict() -> None:
    client = _StubClient(
        '{"relationship_type":"PART_OF","relationship_subtype":"PRODUCT",'
        '"primary_domain":"parent.test","secondary_domain":"child.test",'
        '"evidence_quote":"a product of Parent","reasoning":"child is a product",'
        '"confidence":0.82}'
    )
    verdict = LlmRelationshipVerifier(client).verify(_view("child.test"), _view("parent.test"))
    assert verdict is not None
    assert verdict.relationship_type is RelationshipType.PART_OF
    assert verdict.relationship_subtype is PartOfSubtype.PRODUCT
    assert verdict.primary_domain == "parent.test"
    assert verdict.confidence == 0.82
    assert verdict.model == "stub-model"


def test_verifier_extracts_json_wrapped_in_text() -> None:
    client = _StubClient('Here is my answer: {"relationship_type":"UNRELATED"} — done')
    verdict = LlmRelationshipVerifier(client).verify(_view("a.test"), _view("b.test"))
    assert verdict is not None
    assert verdict.relationship_type is RelationshipType.UNRELATED


def test_verifier_returns_none_on_bad_json() -> None:
    verdict = LlmRelationshipVerifier(_StubClient("not json at all")).verify(
        _view("a.test"), _view("b.test")
    )
    assert verdict is None


def test_verifier_returns_none_on_unknown_type() -> None:
    verdict = LlmRelationshipVerifier(_StubClient('{"relationship_type":"FRIENDS"}')).verify(
        _view("a.test"), _view("b.test")
    )
    assert verdict is None


def test_verifier_returns_none_on_client_error() -> None:
    # A transport error must never break the pipeline -> None (keep deterministic).
    verdict = LlmRelationshipVerifier(_BoomClient()).verify(_view("a.test"), _view("b.test"))
    assert verdict is None


def test_confidence_is_clamped() -> None:
    client = _StubClient('{"relationship_type":"SAME_AS","confidence":5}')
    verdict = LlmRelationshipVerifier(client).verify(_view("a.test"), _view("b.test"))
    assert verdict is not None and verdict.confidence == 1.0
