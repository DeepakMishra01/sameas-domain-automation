"""Unit tests for the hosting / parked / for-sale / broker page detector."""

from typing import Any
from uuid import uuid4

from domain_resolver.classification.hosting_signals import is_hosting_or_parked
from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.views import DomainFeatureView


def _view(host: str, **overrides: Any) -> DomainFeatureView:
    features = FeatureSet(
        feature_version="v",
        domain_id=str(uuid4()),
        observation_id=str(uuid4()),
        normalized_domain=host,
        **overrides,
    )
    return DomainFeatureView(
        domain_id=uuid4(), observation_id=uuid4(), host=host, features=features
    )


def test_for_sale_text_is_detected() -> None:
    assert is_hosting_or_parked(
        _view("x.test", normalized_text_excerpt="This domain is for sale. Buy this domain.")
    )


def test_parked_text_is_detected() -> None:
    assert is_hosting_or_parked(
        _view("x.test", normalized_title="Parked domain", normalized_text_excerpt="domain parking")
    )


def test_placeholder_page_is_detected() -> None:
    assert is_hosting_or_parked(_view("x.test", normalized_title="Welcome to nginx!"))


def test_broker_brand_in_names_is_detected() -> None:
    assert is_hosting_or_parked(_view("x.test", brand_keys=["seghost"]))


def test_broker_token_in_text_is_detected() -> None:
    assert is_hosting_or_parked(
        _view("x.test", normalized_text_excerpt="page provided by parkingcrew network")
    )


def test_real_business_page_is_not_flagged() -> None:
    assert not is_hosting_or_parked(
        _view(
            "acme.test",
            normalized_title="Acme Analytics — Customer Data Platform",
            normalized_meta_description="Acme helps teams understand their customers.",
            normalized_text_excerpt="We build analytics software for enterprise teams.",
            brand_keys=["acme"],
        )
    )


def test_empty_features_are_not_flagged() -> None:
    assert not is_hosting_or_parked(_view("x.test"))
