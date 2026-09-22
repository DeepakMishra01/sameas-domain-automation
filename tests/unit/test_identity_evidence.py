"""Unit tests for the identity-evidence layer (Stage 2B)."""

from typing import Any
from uuid import uuid4

from domain_resolver.classification.identity_evidence import (
    IdentitySignalType,
    compute_identity_evidence,
    has_strong_identity,
)
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


def _types(ev: list[Any]) -> set[IdentitySignalType]:
    return {e.signal_type for e in ev}


def test_shared_analytics_id_is_strong() -> None:
    a = _view("a.test", analytics_ids=["UA-12345-1"])
    b = _view("b.test", analytics_ids=["UA-12345-1"])
    ev = compute_identity_evidence(a, b)
    assert IdentitySignalType.SHARED_ANALYTICS_ID in _types(ev)
    assert has_strong_identity(ev)


def test_shared_gtm_id_is_strong() -> None:
    a = _view("a.test", gtm_ids=["GTM-ABCD1"])
    b = _view("b.test", gtm_ids=["GTM-ABCD1"])
    assert has_strong_identity(compute_identity_evidence(a, b))


def test_shared_tls_fingerprint_is_very_strong() -> None:
    a = _view("a.test", tls_fingerprint="deadbeef")
    b = _view("b.test", tls_fingerprint="deadbeef")
    ev = compute_identity_evidence(a, b)
    assert IdentitySignalType.SHARED_TLS_CERTIFICATE in _types(ev)
    assert has_strong_identity(ev)


def test_tls_san_covering_peer_is_strong() -> None:
    a = _view("a.test", tls_sans=["a.test", "b.test"])
    b = _view("b.test", tls_sans=["b.test"])
    ev = compute_identity_evidence(a, b)
    assert IdentitySignalType.SHARED_TLS_SAN in _types(ev)
    assert has_strong_identity(ev)


def test_org_name_match_is_supporting_not_strong() -> None:
    # A shared organization name is supporting only (names can be embedded or
    # coincidental) — it must not lift a pair out of UNRELATED on its own.
    a = _view("a.test", org_names=["acme technologies"])
    b = _view("b.test", org_names=["acme technologies"])
    ev = compute_identity_evidence(a, b)
    assert IdentitySignalType.ORGANIZATION_NAME_MATCH in _types(ev)
    assert not has_strong_identity(ev)


def test_brand_match_alone_is_supporting_not_strong() -> None:
    # Same brand key, nothing else -> supporting, must NOT be "strong identity".
    a = _view("onegalaxy.test", brand_keys=["onegalaxy"])
    b = _view("onegalaxyltd.test", brand_keys=["onegalaxyltd"])
    ev = compute_identity_evidence(a, b)
    assert IdentitySignalType.BRAND_NAME_MATCH in _types(ev)  # prefix match fires
    assert not has_strong_identity(ev)  # but it is only supporting


def test_short_brand_stub_does_not_prefix_match() -> None:
    a = _view("a.test", brand_keys=["one"])
    b = _view("b.test", brand_keys=["oneworldwidegroup"])
    assert IdentitySignalType.BRAND_NAME_MATCH not in _types(compute_identity_evidence(a, b))


def test_content_fingerprint_match_is_strong() -> None:
    a = _view("a.test", content_hash="H")
    b = _view("b.test", content_hash="H")
    assert has_strong_identity(compute_identity_evidence(a, b))


def test_copyright_year_is_not_an_identity_match() -> None:
    # Two unrelated sites both showing "© 2026" must NOT be linked as one entity.
    a = _view("a.test", org_names=["2026"], copyright_owner="2026", brand_keys=["2026"])
    b = _view("b.test", org_names=["2026"], copyright_owner="2026", brand_keys=["2026"])
    ev = compute_identity_evidence(a, b)
    assert ev == []
    assert not has_strong_identity(ev)


def test_no_identity_evidence() -> None:
    assert compute_identity_evidence(_view("a.test"), _view("b.test")) == []
