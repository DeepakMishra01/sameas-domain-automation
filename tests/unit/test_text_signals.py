"""Unit tests for deterministic PART_OF / ACQUIRED text-signal detection."""

from typing import Any
from uuid import uuid4

from domain_resolver.classification.reason_codes import ClassificationReasonCode
from domain_resolver.classification.relationship_types import PartOfSubtype, RelationshipType
from domain_resolver.classification.text_signals import detect_text_signals
from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.views import DomainFeatureView


def _view(host: str, **overrides: Any) -> DomainFeatureView:
    did = uuid4()
    features = FeatureSet(
        feature_version="v",
        domain_id=str(did),
        observation_id=str(uuid4()),
        normalized_domain=host,
        **overrides,
    )
    return DomainFeatureView(domain_id=did, observation_id=uuid4(), host=host, features=features)


def test_subsidiary_phrase_detected_when_peer_named_in_text() -> None:
    carrier = _view("acme.test", normalized_text_excerpt="acme is a subsidiary of bigparent inc")
    peer = _view("bigparent.test")
    signals = detect_text_signals(carrier, peer)
    assert any(s.reason_code is ClassificationReasonCode.SUBSIDIARY_OF for s in signals)
    signal = next(s for s in signals if s.reason_code is ClassificationReasonCode.SUBSIDIARY_OF)
    assert signal.relationship_type is RelationshipType.PART_OF
    assert signal.subtype is PartOfSubtype.SUBSIDIARY
    assert signal.carrier_is_subordinate is True


def test_peer_named_via_outbound_link_even_if_not_in_text() -> None:
    carrier = _view(
        "acme.test",
        normalized_text_excerpt="acme is a subsidiary of our parent company",
        referenced_domains=["bigparent.test"],
    )
    peer = _view("bigparent.test")
    signals = detect_text_signals(carrier, peer)
    assert any(s.reason_code is ClassificationReasonCode.SUBSIDIARY_OF for s in signals)


def test_no_signal_when_peer_not_named() -> None:
    carrier = _view("acme.test", normalized_text_excerpt="acme is a subsidiary of some company")
    peer = _view("bigparent.test")
    assert detect_text_signals(carrier, peer) == []


def test_acquisition_announcement_is_superior_carrier() -> None:
    carrier = _view("buyer.test", normalized_text_excerpt="buyer has acquired seller last year")
    peer = _view("seller.test")
    signals = detect_text_signals(carrier, peer)
    signal = next(
        s for s in signals if s.reason_code is ClassificationReasonCode.ACQUISITION_ANNOUNCEMENT
    )
    assert signal.relationship_type is RelationshipType.ACQUIRED
    assert signal.carrier_is_subordinate is False


def test_acquired_by_is_subordinate_carrier() -> None:
    carrier = _view("seller.test", normalized_text_excerpt="seller was acquired by buyer group")
    peer = _view("buyer.test")
    signal = next(
        s
        for s in detect_text_signals(carrier, peer)
        if s.reason_code is ClassificationReasonCode.ACQUIRED_BY
    )
    assert signal.carrier_is_subordinate is True


def test_empty_text_yields_no_signals() -> None:
    assert detect_text_signals(_view("a.test"), _view("b.test")) == []
