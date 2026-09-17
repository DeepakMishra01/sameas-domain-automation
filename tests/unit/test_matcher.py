"""Unit tests for the deterministic organization matcher (no DB/network)."""

from typing import Any
from uuid import UUID, uuid4

from domain_resolver.features.results import FeatureSet, SocialProfile
from domain_resolver.matching.config import MatcherConfig
from domain_resolver.matching.matcher import ConfidenceBand, OrganizationMatcher
from domain_resolver.matching.reason_codes import MatchReasonCode
from domain_resolver.matching.views import DomainFeatureView

MATCHER = OrganizationMatcher()


def _view(host: str, domain_id: UUID | None = None, **overrides: Any) -> DomainFeatureView:
    domain_id = domain_id or uuid4()
    observation_id = uuid4()
    features = FeatureSet(
        feature_version="feature-extractor-test",
        domain_id=str(domain_id),
        observation_id=str(observation_id),
        normalized_domain=host,
        **overrides,
    )
    return DomainFeatureView(
        domain_id=domain_id, observation_id=observation_id, host=host, features=features
    )


def test_redirect_only_is_high_confidence_match() -> None:
    a = _view("secondary.test", has_redirect=True, redirect_target_domain="primary.test")
    b = _view("primary.test")
    result = MATCHER.match(a, b)
    assert result.same_organization is True
    assert result.confidence_band is ConfidenceBand.HIGH
    assert MatchReasonCode.REDIRECT in result.reason_codes


def test_canonical_only_matches() -> None:
    a = _view("a.test", canonical_domain="b.test")
    b = _view("b.test")
    result = MATCHER.match(a, b)
    assert result.same_organization is True
    assert MatchReasonCode.CANONICAL_URL in result.reason_codes


def test_cross_reference_only_matches() -> None:
    a = _view("a.test", referenced_domains=["b.test"])
    b = _view("b.test")
    result = MATCHER.match(a, b)
    assert result.same_organization is True
    assert MatchReasonCode.CROSS_DOMAIN_REFERENCE in result.reason_codes


def test_mutual_cross_reference_is_very_strong() -> None:
    a = _view("a.test", referenced_domains=["b.test"])
    b = _view("b.test", referenced_domains=["a.test"])
    result = MATCHER.match(a, b)
    assert MatchReasonCode.CROSS_DOMAIN_REFERENCE_MUTUAL in result.reason_codes
    assert result.confidence_band is ConfidenceBand.HIGH


def test_same_email_domain_only_matches() -> None:
    a = _view("a.test", email_domains=["corp.example"])
    b = _view("b.test", email_domains=["corp.example"])
    result = MATCHER.match(a, b)
    assert result.same_organization is True
    assert MatchReasonCode.SAME_EMAIL_DOMAIN in result.reason_codes


def test_same_phone_only_matches() -> None:
    a = _view("a.test", phone_numbers=["+14155550000"])
    b = _view("b.test", phone_numbers=["+14155550000"])
    result = MATCHER.match(a, b)
    assert result.same_organization is True
    assert MatchReasonCode.SAME_PHONE in result.reason_codes


def test_same_social_profile_only_matches() -> None:
    profile = [SocialProfile(platform="linkedin", url="https://linkedin.com/company/x")]
    a = _view("a.test", social_profiles=profile)
    b = _view("b.test", social_profiles=profile)
    result = MATCHER.match(a, b)
    assert result.same_organization is True
    assert MatchReasonCode.SAME_SOCIAL_PROFILE in result.reason_codes


def test_similar_name_alone_is_not_enough() -> None:
    a = _view("acme-inc.test")
    b = _view("acmeinc.test")
    result = MATCHER.match(a, b)
    assert MatchReasonCode.DOMAIN_NAME_SIMILARITY in result.reason_codes
    assert result.same_organization is False  # weak evidence alone never matches
    assert result.confidence_band is ConfidenceBand.LOW


def test_no_evidence_is_not_a_match() -> None:
    result = MATCHER.match(_view("one.test"), _view("two.test"))
    assert result.same_organization is False
    assert result.reason_codes == []
    assert result.confidence == 0.0


def test_conflicting_evidence_lowers_but_can_still_match() -> None:
    a = _view("a.test", email_domains=["corp.example"], phone_numbers=["+111111111"])
    b = _view("b.test", email_domains=["corp.example"], phone_numbers=["+222222222"])
    result = MATCHER.match(a, b)
    assert MatchReasonCode.SAME_EMAIL_DOMAIN in result.reason_codes
    assert MatchReasonCode.DIFFERENT_PHONE in result.negative_reason_codes
    # A single contradiction dampens confidence but does not auto-reject here.
    assert result.same_organization is True
    assert result.confidence < 0.7


def test_result_is_canonical_and_symmetric() -> None:
    low = UUID("00000000-0000-0000-0000-000000000001")
    high = UUID("00000000-0000-0000-0000-000000000002")
    a = _view("a.test", low, referenced_domains=["b.test"])
    b = _view("b.test", high, referenced_domains=["a.test"])
    forward = MATCHER.match(a, b)
    reverse = MATCHER.match(b, a)
    assert forward.domain_a_id == reverse.domain_a_id == low
    assert forward.domain_b_id == reverse.domain_b_id == high
    assert forward.same_organization == reverse.same_organization
    assert forward.confidence == reverse.confidence


def test_matcher_version_is_recorded() -> None:
    matcher = OrganizationMatcher(MatcherConfig(version="org-matcher-test-v9"))
    result = matcher.match(_view("a.test", referenced_domains=["b.test"]), _view("b.test"))
    assert result.matcher_version == "org-matcher-test-v9"
