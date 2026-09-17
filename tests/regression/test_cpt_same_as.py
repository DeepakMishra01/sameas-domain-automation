"""Regression tests for the organization matcher.

Two parts:

1. A controlled synthetic labelled set that exercises each supported evidence
   type (positive) and clear non-matches (negative). It locks in that a future
   change cannot silently break a previously supported signal — measured via the
   real evaluation harness (expects perfect precision/recall on this set).
2. The 14 CPT Same-As examples treated as evaluation data only. They are NOT
   hard-coded into the matcher and their connecting evidence is NOT fabricated:
   with no observations the deterministic baseline predicts no match, which this
   test asserts to guarantee the matcher never matches without evidence.
"""

import csv
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from domain_resolver.features.results import FeatureSet, SocialProfile
from domain_resolver.matching.evaluation import evaluate
from domain_resolver.matching.matcher import MatchResult, OrganizationMatcher
from domain_resolver.matching.views import DomainFeatureView

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "same_as_examples.csv"
MATCHER = OrganizationMatcher()


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


def _match(a_over: dict[str, Any], b_over: dict[str, Any]) -> MatchResult:
    low, high = sorted((uuid4(), uuid4()))
    return MATCHER.match(_view("aaa.example", low, **a_over), _view("bbb.example", high, **b_over))


def test_each_supported_evidence_type_is_locked_in() -> None:
    profile = [SocialProfile(platform="linkedin", url="https://linkedin.com/company/x")]
    positives = [
        ({"has_redirect": True, "redirect_target_domain": "bbb.example"}, {}),
        ({"canonical_domain": "bbb.example"}, {}),
        ({"referenced_domains": ["bbb.example"]}, {"referenced_domains": ["aaa.example"]}),
        ({"email_domains": ["corp.z"]}, {"email_domains": ["corp.z"]}),
        ({"phone_numbers": ["+15550001111"]}, {"phone_numbers": ["+15550001111"]}),
        ({"social_profiles": profile}, {"social_profiles": profile}),
        ({"content_hash": "same"}, {"content_hash": "same"}),
    ]
    negatives = [
        ({}, {}),  # no evidence
        ({"email_domains": ["one.z"]}, {"email_domains": ["two.z"]}),  # contradiction only
    ]

    items: list[tuple[bool, MatchResult]] = []
    items.extend((True, _match(a, b)) for a, b in positives)
    items.extend((False, _match(a, b)) for a, b in negatives)

    report = evaluate(items)
    assert report.recall == 1.0  # every supported evidence type still matches
    assert report.precision == 1.0  # no non-match is wrongly matched
    assert report.f1 == 1.0
    assert report.reason_code_counts  # explainable: reason codes were recorded


def test_cpt_examples_load_as_evaluation_data() -> None:
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 14
    assert {row["label_source"] for row in rows} == {"CPT_GOLD"}
    assert all(row["secondary_domain"] != row["primary_domain"] for row in rows)


def test_matcher_never_matches_without_evidence() -> None:
    # No hard-coded CPT rules: with no observed features, no CPT pair matches.
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    items: list[tuple[bool, MatchResult]] = []
    for row in rows:
        low, high = sorted((uuid4(), uuid4()))
        result = MATCHER.match(
            _view(row["secondary_domain"], low), _view(row["primary_domain"], high)
        )
        items.append((True, result))
    report = evaluate(items)
    # The deterministic baseline makes zero unsupported claims (recall 0 here is
    # expected: these domains have not been observed in this test environment).
    assert report.true_positives == 0
    assert report.false_positives == 0
    assert all(not outcome.predicted_same_org for outcome in report.outcomes)
