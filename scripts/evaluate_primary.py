#!/usr/bin/env python
"""Evaluate primary-domain resolution on the 14 CPT Same-As examples.

Each CPT example is treated as a confirmed same-organization group (per the gold
labels), so Phase 5 matching is not on trial here. For each pair this observes
both domains (Phase 3), extracts features (Phase 4), resolves the primary
(Phase 6), and checks it against the expected primary — reporting accuracy,
coverage, confidence distribution, and the reason codes responsible.

Requires ``DERE_DATABASE_URL``. The observer makes outbound requests; the
resolver itself makes no network calls. Evaluation utility, not a test.
"""

from __future__ import annotations

import csv
from pathlib import Path
from uuid import uuid4

from domain_resolver.config.settings import get_settings
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.infrastructure.database import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.models.entities import Company, Domain
from domain_resolver.normalization import normalize_domain
from domain_resolver.observation.dns_observer import DnsObserver
from domain_resolver.observation.http_observer import HttpObserver
from domain_resolver.observation.service import run_domain_observation
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyDomainRepository,
    SqlAlchemyObservationFeatureRepository,
)
from domain_resolver.resolution.evaluation import evaluate_primary
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.results import PrimaryResolution

FIXTURE_PATH = Path(__file__).parents[1] / "tests" / "fixtures" / "same_as_examples.csv"


def _prepare(session: object, company_id: object, host: str) -> DomainFeatureView | None:
    domains = SqlAlchemyDomainRepository(session)
    domain = domains.get_by_hostname(host) or domains.create(Domain(hostname=host))
    observation = run_domain_observation(
        session,
        company_id=company_id,  # type: ignore[arg-type]
        domain_id=domain.id,
        idempotency_key=uuid4().hex,
        collector_version=get_settings().collector_version,
        dns_observer=DnsObserver(),
        http_observer=HttpObserver(),
    )
    run_feature_extraction(
        session,
        observation_id=observation.id,
        extractor=FeatureExtractor(get_settings().feature_extractor_version),
    )
    snapshots = SqlAlchemyObservationFeatureRepository(session).list_by_domain(domain.id)
    return DomainFeatureView.from_snapshot(snapshots[-1], host) if snapshots else None


def main() -> None:
    settings = get_settings()
    factory = create_session_factory(create_engine_from_settings(settings))
    resolver = PrimaryDomainResolver()

    with FIXTURE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    items: list[tuple[str, PrimaryResolution]] = []
    for index, row in enumerate(rows, start=1):
        secondary = normalize_domain(row["secondary_domain"])
        primary = normalize_domain(row["primary_domain"])
        with session_scope(factory) as session:
            company = Company(
                external_company_id=f"cpt-primary-{index}",
                name_raw=f"CPT {index}",
                name_normalized=f"cpt {index}",
            )
            session.add(company)
            session.flush()
            view_a = _prepare(session, company.id, secondary)
            view_b = _prepare(session, company.id, primary)
        views = [v for v in (view_a, view_b) if v is not None]
        if len(views) < 2:
            print(f"[{index:2}] {secondary} / {primary}: no observations (skipped)")
            continue
        resolution = resolver.resolve(views)
        items.append((primary, resolution))
        print(
            f"[{index:2}] expected primary={primary:28} "
            f"status={resolution.status.value:15} got={resolution.primary_host} "
            f"conf={resolution.confidence}"
        )

    report = evaluate_primary(items)
    print("\n=== CPT primary-domain evaluation ===")
    print(f"evaluated groups : {report.total}")
    print(f"resolved         : {report.resolved}  unresolved: {report.unresolved}")
    print(f"correct          : {report.correct}  incorrect: {report.incorrect}")
    print(f"coverage         : {report.coverage}")
    print(f"accuracy(resolved): {report.accuracy_over_resolved}")
    print(f"overall accuracy : {report.overall_accuracy}")
    print(f"bands            : {report.band_counts}")
    print(f"reason codes     : {report.reason_code_counts}")


if __name__ == "__main__":
    main()
