"""Unit tests for deterministic same-brand / regional-variant detection."""

from typing import Any
from uuid import uuid4

from domain_resolver.classification.name_relation import detect_name_relation, registrable_name
from domain_resolver.classification.relationship_types import PartOfSubtype
from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.views import DomainFeatureView


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


def test_registrable_name_handles_second_level_tlds() -> None:
    assert registrable_name("carsforstars-brighton.co.uk") == "carsforstars-brighton"
    assert registrable_name("febino.com") == "febino"
    assert registrable_name("shop.example.com.au") == "example"


def test_same_name_different_tld_is_part_of() -> None:
    rel = detect_name_relation(_view("febino.in"), _view("febino.com"))
    assert rel is not None
    assert rel.subtype is PartOfSubtype.REGIONAL_ENTITY
    assert rel.parent.host == "febino.com"  # global TLD preferred as parent
    assert rel.child.host == "febino.in"


def test_branch_prefix_is_part_of_parent() -> None:
    rel = detect_name_relation(_view("carsforstars-brighton.co.uk"), _view("carsforstars.net"))
    assert rel is not None
    assert rel.parent.host == "carsforstars.net"  # shorter/base name is the parent
    assert rel.child.host == "carsforstars-brighton.co.uk"


def test_glued_lookalike_names_do_not_match() -> None:
    # "guardianvoices" is a single glued token; it must NOT link to "theguardian".
    assert detect_name_relation(_view("guardianvoices.co.uk"), _view("theguardian.com")) is None


def test_generic_shared_word_does_not_match() -> None:
    assert detect_name_relation(_view("security.com"), _view("security.in")) is None


def test_one_way_reference_sets_parent_direction() -> None:
    # a.in links to a.com and not vice-versa -> a.com is parent.
    a = _view("acmebrand.in", referenced_domains=["acmebrand.com"])
    b = _view("acmebrand.com")
    rel = detect_name_relation(a, b)
    assert rel is not None and rel.parent.host == "acmebrand.com"


def test_unrelated_names_return_none() -> None:
    assert detect_name_relation(_view("coppellfootball.com"), _view("athdynasty.com")) is None
