"""Regression tests for the relationship classifier.

Two parts:

1. A controlled **synthetic** labelled set (clearly not CPT gold) that exercises
   each relationship type and locks in that a future change cannot silently
   regress a category — with a dedicated assertion that PART_OF / ACQUIRED /
   related-no-redirect pairs are NEVER classified SAME_AS (the SOP's critical
   error, §22).
2. The 14 CPT Same-As examples: with no observations the classifier must NOT
   emit SAME_AS for any of them, guaranteeing no hard-coded CPT rules and that
   SAME_AS is never produced without an observed redirect.
"""

import csv
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from domain_resolver.classification.classifier import RelationshipClassifier
from domain_resolver.classification.relationship_types import RelationshipType
from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.matching.views import DomainFeatureView

FIXTURES = Path(__file__).parents[1] / "fixtures"
REL_FIXTURE = FIXTURES / "relationship_examples.csv"
SAME_AS_FIXTURE = FIXTURES / "same_as_examples.csv"

MATCHER = OrganizationMatcher()
CLASSIFIER = RelationshipClassifier()


def _view(host: str, domain_id: UUID, **overrides: Any) -> DomainFeatureView:
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


def _features_for(scenario: str, a_host: str, b_host: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Representative synthetic features that a real observation of each scenario
    would produce (no hard-coding of the classifier — it only sees features)."""
    b_name = b_host.split(".")[0]
    a_name = a_host.split(".")[0]
    if scenario in {"zepto_redirect", "old_to_new_redirect"}:
        return {"has_redirect": True, "redirect_target_domain": b_host}, {}
    if scenario == "amazon_primevideo_product":
        return {"normalized_text_excerpt": f"{a_name} is a product of {b_name}"}, {}
    if scenario == "subsidiary_statement":
        return {"normalized_text_excerpt": f"{a_name} is a subsidiary of {b_name}"}, {}
    if scenario == "flipkart_myntra_acquired":
        return {"normalized_text_excerpt": f"{a_name} was acquired by {b_name} in 2014"}, {}
    if scenario == "shared_contacts_no_redirect":
        return (
            {"email_domains": ["shared.example"], "phone_numbers": ["+15551230000"]},
            {"email_domains": ["shared.example"], "phone_numbers": ["+15551230000"]},
        )
    if scenario == "canonical_without_content":
        return {"has_canonical": True, "canonical_domain": b_host, "content_hash": "AAA"}, {
            "content_hash": "BBB"
        }
    return {}, {}  # unrelated_pair: no evidence


def test_relationship_fixture_is_labelled_synthetic() -> None:
    with REL_FIXTURE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "fixture must not be empty"
    # Honesty guard: these are NOT CPT gold data.
    assert {row["label_source"] for row in rows} == {"SYNTHETIC"}


def test_each_relationship_type_is_classified_correctly() -> None:
    with REL_FIXTURE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    same_as_false_positives = 0
    for row in rows:
        low, high = sorted((uuid4(), uuid4()))
        a_over, b_over = _features_for(row["scenario"], row["domain_a"], row["domain_b"])
        view_a = _view(row["domain_a"], low, **a_over)
        view_b = _view(row["domain_b"], high, **b_over)
        match = MATCHER.match(view_a, view_b)
        result = CLASSIFIER.classify(view_a, view_b, match)

        expected = RelationshipType(row["expected_type"])
        assert result.relationship_type is expected, (
            f"{row['scenario']}: expected {expected}, got {result.relationship_type} "
            f"({result.reason_codes})"
        )
        if row["expected_primary"]:
            assert result.primary_host == row["expected_primary"], row["scenario"]
        # Critical SOP invariant: only genuinely-SAME_AS scenarios may be SAME_AS.
        if expected is not RelationshipType.SAME_AS and result.relationship_type is (
            RelationshipType.SAME_AS
        ):
            same_as_false_positives += 1
    assert same_as_false_positives == 0


def test_classifier_never_emits_same_as_without_observation() -> None:
    # The 14 CPT gold pairs, unobserved: no redirect features -> never SAME_AS.
    with SAME_AS_FIXTURE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 14
    for row in rows:
        low, high = sorted((uuid4(), uuid4()))
        view_a = _view(row["secondary_domain"], low)
        view_b = _view(row["primary_domain"], high)
        match = MATCHER.match(view_a, view_b)
        result = CLASSIFIER.classify(view_a, view_b, match)
        assert result.relationship_type is not RelationshipType.SAME_AS
