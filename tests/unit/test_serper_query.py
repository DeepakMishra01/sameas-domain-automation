"""Unit tests for building Serper relationship/identity queries from a pair."""

from typing import Any
from uuid import uuid4

from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.search.query import build_relationship_queries, entity_name


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


# ------------------------------------------------------------- entity_name
def test_entity_name_prefers_org_name() -> None:
    v = _view("careerlynetworks.com", org_names=["Careerly Networks"], normalized_title="Home")
    assert entity_name(v) == "Careerly Networks"


def test_entity_name_falls_back_to_title_head() -> None:
    v = _view(
        "ai-scientific-coinvestigator-ui.vercel.app",
        normalized_title="SCoinvestigator AI | Advanced Research",
    )
    assert entity_name(v) == "SCoinvestigator AI"


def test_entity_name_falls_back_to_hostname_label() -> None:
    # No org/title/brand -> derive a label from the host, stripping infra suffix.
    v = _view("ai-scientific-coinvestigator-ui.vercel.app")
    assert "scientific" in entity_name(v).lower()
    assert "vercel" not in entity_name(v).lower()


def test_entity_name_plain_domain_label() -> None:
    assert entity_name(_view("careerly.live")) == "careerly"


# ------------------------------------------------ build_relationship_queries
def test_relationship_query_for_different_names() -> None:
    a = _view("careerly.live", org_names=["Careerly"])
    b = _view("careerlynetworks.com", org_names=["Careerly Networks"])
    qs = build_relationship_queries(a, b, max_queries=2)
    assert len(qs) == 2
    # first is the relationship query naming both entities + relationship keywords
    assert "Careerly" in qs[0] and "Careerly Networks" in qs[0]
    assert "acquired" in qs[0] and "subsidiary" in qs[0]
    # second is the identity/knowledge-graph query with the clean domain
    assert "careerlynetworks.com" in qs[1] and "company" in qs[1]


def test_no_raw_infra_host_in_queries() -> None:
    a = _view(
        "ai-scientific-coinvestigator-ui.vercel.app",
        normalized_title="SCoinvestigator AI | Research",
    )
    b = _view("scoinvestigator.com", org_names=["SCoinvestigator"])
    qs = build_relationship_queries(a, b, max_queries=2)
    joined = " ".join(qs)
    assert "vercel.app" not in joined
    assert "SCoinvestigator" in joined


def test_same_brand_pair_uses_identity_queries() -> None:
    # Same brand, different TLD -> a joint relationship query is useless; emit an
    # identity query per side so the LLM can tell "same company" from "same name".
    a = _view("techgrow.co.in", org_names=["TechGrow"], brand_keys=["techgrow"])
    b = _view("techgrow.in", org_names=["TechGrow"], brand_keys=["techgrow"])
    qs = build_relationship_queries(a, b, max_queries=2)
    assert len(qs) == 2
    assert all("company" in q for q in qs)
    assert any("techgrow.co.in" in q for q in qs)
    assert any("techgrow.in" in q for q in qs)
    # not the relationship keyword form
    assert not any("acquired" in q for q in qs)


def test_max_queries_one_returns_single_query() -> None:
    a = _view("careerly.live", org_names=["Careerly"])
    b = _view("careerlynetworks.com", org_names=["Careerly Networks"])
    qs = build_relationship_queries(a, b, max_queries=1)
    assert len(qs) == 1


def test_multiword_names_are_quoted() -> None:
    # Genuinely different roots -> relationship query with both names quoted.
    a = _view("borisfx.com", org_names=["Boris FX"])
    b = _view("samplitude.com", org_names=["Samplitude Studio"])
    qs = build_relationship_queries(a, b, max_queries=1)
    assert '"Boris FX"' in qs[0]
    assert '"Samplitude Studio"' in qs[0]


def test_same_root_different_suffix_uses_identity_queries() -> None:
    # "Ventureprise Holding" vs "Ventureprise Group": same root, possibly DIFFERENT
    # companies -> disambiguate each identity rather than a joint relationship query.
    a = _view("venturepriseholding.com", org_names=["Ventureprise Holding"])
    b = _view("ventureprisegroup.com", org_names=["Ventureprise Group"])
    qs = build_relationship_queries(a, b, max_queries=2)
    assert len(qs) == 2
    assert all("company" in q for q in qs)
    assert any("venturepriseholding.com" in q for q in qs)
    assert any("ventureprisegroup.com" in q for q in qs)
