"""Regression tests for primary-domain resolution.

Locks in that directional evidence resolves the primary correctly (via the real
evaluation harness), and that the 14 CPT examples — evaluation data only, never
hard-coded — are never "resolved" without directional evidence.
"""

import csv
from pathlib import Path
from uuid import uuid4

from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.resolution.evaluation import evaluate_primary
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.results import PrimaryResolution, ResolutionStatus

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "same_as_examples.csv"
RESOLVER = PrimaryDomainResolver()


def _view(
    host: str, *, redirect_to: str | None = None, title: str | None = None
) -> DomainFeatureView:
    domain_id = uuid4()
    features = FeatureSet(
        feature_version="v",
        domain_id=str(domain_id),
        observation_id=str(uuid4()),
        normalized_domain=host,
        has_redirect=redirect_to is not None,
        redirect_target_domain=redirect_to,
        final_domain=redirect_to or host,
        normalized_title=title,
    )
    return DomainFeatureView(
        domain_id=domain_id, observation_id=uuid4(), host=host, features=features
    )


def test_directional_evidence_resolves_expected_primary() -> None:
    items: list[tuple[str, PrimaryResolution]] = []
    for i in range(5):
        secondary, primary = f"sec{i}.test", f"pri{i}.test"
        resolution = RESOLVER.resolve(
            [_view(secondary, redirect_to=primary), _view(primary, title="P")]
        )
        items.append((primary, resolution))
    report = evaluate_primary(items)
    assert report.overall_accuracy == 1.0
    assert report.coverage == 1.0
    assert "REDIRECT_TARGET" in report.reason_code_counts


def test_cpt_examples_load_as_evaluation_data() -> None:
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 14
    assert all(row["secondary_domain"] != row["primary_domain"] for row in rows)


def test_resolver_never_resolves_without_directional_evidence() -> None:
    # No hard-coded CPT answers: with no observed features, no pair resolves.
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        resolution = RESOLVER.resolve(
            [_view(row["secondary_domain"]), _view(row["primary_domain"])]
        )
        assert resolution.status is ResolutionStatus.REVIEW_REQUIRED
        assert resolution.primary_domain_id is None
