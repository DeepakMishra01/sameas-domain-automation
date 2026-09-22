"""Unit tests for the deterministic relationship classifier (no DB/network).

Covers the SOP §20 categories: SAME_AS (redirect required), PART_OF, ACQUIRED,
UNRELATED, and the REVIEW_REQUIRED safety net. The central invariant is that
shared name / phone / email / social / content / cross-links must NOT produce
SAME_AS without an observed redirect.
"""

from typing import Any
from uuid import UUID, uuid4

from domain_resolver.classification.classifier import RelationshipClassifier
from domain_resolver.classification.config import ClassifierConfig
from domain_resolver.classification.reason_codes import ClassificationReasonCode
from domain_resolver.classification.relationship_types import (
    PartOfSubtype,
    RelationshipDirection,
    RelationshipType,
)
from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.matcher import ConfidenceBand, MatchResult
from domain_resolver.matching.reason_codes import MatchReasonCode
from domain_resolver.matching.views import DomainFeatureView

CLASSIFIER = RelationshipClassifier()


def _view(host: str, domain_id: UUID | None = None, **overrides: Any) -> DomainFeatureView:
    domain_id = domain_id or uuid4()
    features = FeatureSet(
        feature_version="v",
        domain_id=str(domain_id),
        observation_id=str(uuid4()),
        normalized_domain=host,
        **overrides,
    )
    return DomainFeatureView(
        domain_id=domain_id, observation_id=uuid4(), host=host, features=features
    )


def _match(
    a: DomainFeatureView,
    b: DomainFeatureView,
    *,
    same: bool = False,
    confidence: float = 0.0,
    codes: list[MatchReasonCode] | None = None,
) -> MatchResult:
    lo, hi = (a, b) if a.domain_id < b.domain_id else (b, a)
    return MatchResult(
        domain_a_id=lo.domain_id,
        domain_b_id=hi.domain_id,
        domain_a=lo.host,
        domain_b=hi.host,
        same_organization=same,
        confidence=confidence,
        confidence_band=ConfidenceBand.HIGH if confidence >= 0.8 else ConfidenceBand.LOW,
        reason_codes=codes or [],
        matcher_version="test",
    )


# --------------------------------------------------------------- SAME_AS
def test_redirect_makes_same_as_with_target_primary() -> None:
    a = _view("secondary.test", has_redirect=True, redirect_target_domain="primary.test")
    b = _view("primary.test")
    result = CLASSIFIER.classify(a, b, _match(a, b))
    assert result.relationship_type is RelationshipType.SAME_AS
    assert result.primary_host == "primary.test"
    assert result.secondary_host == "secondary.test"
    assert ClassificationReasonCode.REDIRECT_TO_PRIMARY in result.reason_codes


def test_redirect_chain_makes_same_as() -> None:
    # No direct target match, but the final domain of the chain is the peer.
    a = _view(
        "old.test", has_redirect=True, redirect_target_domain="mid.test", final_domain="new.test"
    )
    b = _view("new.test")
    result = CLASSIFIER.classify(a, b, _match(a, b))
    assert result.relationship_type is RelationshipType.SAME_AS
    assert result.primary_host == "new.test"
    assert ClassificationReasonCode.REDIRECT_CHAIN_TO_PRIMARY in result.reason_codes


def test_mutual_redirect_is_review_conflict() -> None:
    a = _view("a.test", has_redirect=True, redirect_target_domain="b.test")
    b = _view("b.test", has_redirect=True, redirect_target_domain="a.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.95))
    assert result.relationship_type is RelationshipType.REVIEW_REQUIRED
    assert ClassificationReasonCode.MUTUAL_REDIRECT_CONFLICT in result.reason_codes
    assert result.direction is RelationshipDirection.SYMMETRIC


def test_canonical_alone_is_review_not_same_as() -> None:
    a = _view("a.test", has_canonical=True, canonical_domain="b.test")
    b = _view("b.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.9))
    assert result.relationship_type is RelationshipType.REVIEW_REQUIRED
    assert ClassificationReasonCode.CANONICAL_WITHOUT_CORROBORATION in result.reason_codes


def test_canonical_with_identical_content_is_same_as() -> None:
    a = _view("a.test", has_canonical=True, canonical_domain="b.test", content_hash="H")
    b = _view("b.test", content_hash="H")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.9))
    assert result.relationship_type is RelationshipType.SAME_AS
    assert result.primary_host == "b.test"
    assert ClassificationReasonCode.CANONICAL_TO_PRIMARY_CORROBORATED in result.reason_codes


def test_shared_contact_without_redirect_is_not_same_as() -> None:
    # Same email domain + same phone, matcher says related, but NO redirect.
    a = _view("a.test", email_domains=["corp.example"], phone_numbers=["+14155550000"])
    b = _view("b.test", email_domains=["corp.example"], phone_numbers=["+14155550000"])
    result = CLASSIFIER.classify(
        a, b, _match(a, b, same=True, confidence=0.7, codes=[MatchReasonCode.SAME_EMAIL_DOMAIN])
    )
    assert result.relationship_type is RelationshipType.REVIEW_REQUIRED
    assert ClassificationReasonCode.RELATED_TYPE_UNDETERMINED in result.reason_codes


# --------------------------------------------------------------- PART_OF
def test_subsidiary_statement_makes_part_of() -> None:
    a = _view("acme.test", normalized_text_excerpt="acme is a subsidiary of bigparent limited")
    b = _view("bigparent.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.6))
    assert result.relationship_type is RelationshipType.PART_OF
    assert result.relationship_subtype is PartOfSubtype.SUBSIDIARY
    assert result.primary_host == "bigparent.test"  # parent is primary
    assert result.secondary_host == "acme.test"
    assert result.parent_host == "bigparent.test"
    assert result.part_of_host == "acme.test"
    assert ClassificationReasonCode.SUBSIDIARY_OF in result.reason_codes


def test_product_statement_makes_part_of_product() -> None:
    a = _view("widget.test", normalized_text_excerpt="widget is a product of bigparent")
    b = _view("bigparent.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.6))
    assert result.relationship_type is RelationshipType.PART_OF
    assert result.relationship_subtype is PartOfSubtype.PRODUCT


def test_generic_part_of_statement_uses_other_subtype() -> None:
    a = _view("brandx.test", normalized_text_excerpt="brandx is part of the bigparent group")
    b = _view("bigparent.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.6))
    assert result.relationship_type is RelationshipType.PART_OF
    assert result.relationship_subtype is PartOfSubtype.OTHER
    assert ClassificationReasonCode.PART_OF_STATEMENT in result.reason_codes


def test_part_of_phrase_without_naming_peer_is_not_typed() -> None:
    # "part of" present but the peer is never named/linked -> no signal -> REVIEW (related).
    a = _view("brandx.test", normalized_text_excerpt="brandx is part of a large group")
    b = _view("unnamedparent.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.6))
    assert result.relationship_type is RelationshipType.REVIEW_REQUIRED


# --------------------------------------------------------------- ACQUIRED
def test_acquired_by_statement_makes_acquired() -> None:
    a = _view("startup.test", normalized_text_excerpt="startup was acquired by bigacquirer in 2020")
    b = _view("bigacquirer.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.6))
    assert result.relationship_type is RelationshipType.ACQUIRED
    assert result.primary_host == "bigacquirer.test"  # acquirer is primary
    assert result.acquirer_host == "bigacquirer.test"
    assert result.acquired_host == "startup.test"
    assert ClassificationReasonCode.ACQUIRED_BY in result.reason_codes


def test_acquisition_announcement_sets_acquirer_as_carrier() -> None:
    a = _view("bigacquirer.test", normalized_text_excerpt="bigacquirer has acquired startup today")
    b = _view("startup.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.6))
    assert result.relationship_type is RelationshipType.ACQUIRED
    assert result.acquirer_host == "bigacquirer.test"
    assert result.acquired_host == "startup.test"


def test_redirect_wins_over_acquisition_text() -> None:
    # SOP §13 Case A: a redirect present alongside an acquisition phrase -> SAME_AS,
    # with the statement retained in the explanation.
    a = _view(
        "startup.test",
        has_redirect=True,
        redirect_target_domain="bigacquirer.test",
        normalized_text_excerpt="startup was acquired by bigacquirer",
    )
    b = _view("bigacquirer.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.95))
    assert result.relationship_type is RelationshipType.SAME_AS
    assert result.primary_host == "bigacquirer.test"
    assert "acquired by" in result.explanation


def test_contradictory_statements_go_to_review() -> None:
    a = _view("a.test", normalized_text_excerpt="a was acquired by b company")
    b = _view("b.test", normalized_text_excerpt="b was acquired by a company")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=True, confidence=0.6))
    assert result.relationship_type is RelationshipType.REVIEW_REQUIRED
    assert ClassificationReasonCode.CONTRADICTORY_TYPE_SIGNALS in result.reason_codes


# --------------------------------------------------------------- UNRELATED
def test_no_relationship_is_unrelated() -> None:
    a = _view("one.test")
    b = _view("two.test")
    result = CLASSIFIER.classify(a, b, _match(a, b, same=False, confidence=0.0))
    assert result.relationship_type is RelationshipType.UNRELATED
    assert result.primary_host is None
    assert ClassificationReasonCode.NO_CREDIBLE_RELATIONSHIP in result.reason_codes


# --------------------------------------------------------------- meta
def test_result_is_canonical_order_and_deterministic() -> None:
    lo = UUID("00000000-0000-0000-0000-000000000001")
    hi = UUID("00000000-0000-0000-0000-000000000002")
    a = _view("secondary.test", lo, has_redirect=True, redirect_target_domain="primary.test")
    b = _view("primary.test", hi)
    forward = CLASSIFIER.classify(a, b, _match(a, b))
    reverse = CLASSIFIER.classify(b, a, _match(b, a))
    assert forward.domain_a_id == reverse.domain_a_id == lo
    assert forward.relationship_type == reverse.relationship_type
    assert forward.primary_host == reverse.primary_host == "primary.test"


def test_classifier_version_is_recorded() -> None:
    classifier = RelationshipClassifier(ClassifierConfig(version="rc-test-v9"))
    a = _view("a.test", has_redirect=True, redirect_target_domain="b.test")
    b = _view("b.test")
    result = classifier.classify(a, b, _match(a, b))
    assert result.classifier_version == "rc-test-v9"
