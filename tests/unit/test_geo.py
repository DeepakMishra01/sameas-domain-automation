"""Unit tests for the Geographies Served category rule and LLM verifier."""

from uuid import uuid4

from domain_resolver.features.results import FeatureSet
from domain_resolver.geo.category import GLOBAL, MULTINATIONAL, SINGLE, UNKNOWN, categorize
from domain_resolver.geo.verifier import GeoVerifier
from domain_resolver.matching.views import DomainFeatureView


def test_category_rules() -> None:
    assert categorize([]) == UNKNOWN
    assert categorize(["India"]) == SINGLE
    assert categorize(["India", "india ", "INDIA"]) == SINGLE  # de-duplicated
    assert categorize(["US", "UK", "Germany"]) == MULTINATIONAL
    assert categorize([f"Country{i}" for i in range(50)]) == GLOBAL
    assert categorize([f"Country{i}" for i in range(49)]) == MULTINATIONAL


class _Stub:
    model = "stub"

    def __init__(self, resp: str) -> None:
        self._resp = resp

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        return self._resp


class _Boom:
    model = "boom"

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        raise RuntimeError("down")


def _view(host: str = "acme.com") -> DomainFeatureView:
    f = FeatureSet(
        feature_version="v",
        domain_id=str(uuid4()),
        observation_id=str(uuid4()),
        normalized_domain=host,
    )
    return DomainFeatureView(domain_id=uuid4(), observation_id=uuid4(), host=host, features=f)


def test_verifier_parses_countries() -> None:
    v = GeoVerifier(
        _Stub(
            '{"countries":["United States","United Kingdom"],"headquarters":"United States",'
            '"evidence_quote":"offices in US and UK","reasoning":"two offices","confidence":0.8}'
        )
    ).verify(_view(), "Acme")
    assert v is not None
    assert v.countries == ["United States", "United Kingdom"]
    assert v.headquarters == "United States"
    assert v.confidence == 0.8
    assert categorize(v.countries) == MULTINATIONAL


def test_verifier_accepts_comma_string_and_clamps() -> None:
    v = GeoVerifier(_Stub('{"countries":"India, Nepal","confidence":5}')).verify(_view())
    assert v is not None and v.countries == ["India", "Nepal"] and v.confidence == 1.0


def test_verifier_none_on_bad_json_or_error() -> None:
    assert GeoVerifier(_Stub("not json")).verify(_view()) is None
    assert GeoVerifier(_Boom()).verify(_view()) is None
