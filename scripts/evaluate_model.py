#!/usr/bin/env python
"""Evaluate the organization matcher on the 14 CPT Same-As examples.

For each labelled pair this observes both domains (Phase 3, SSRF-safe network),
extracts features (Phase 4), and matches the pair (Phase 5), then reports
precision/recall/F1 and the reason codes responsible. It uses only the
same-organization decision and never the expected-primary information.

Requires ``DERE_DATABASE_URL`` (a disposable database). The observer makes
outbound requests; the matcher itself makes no network calls. This is an
evaluation utility, not part of the deterministic test suite.
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
from domain_resolver.matching.evaluation import evaluate
from domain_resolver.matching.matcher import MatchResult, OrganizationMatcher
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

FIXTURE_PATH = Path(__file__).parents[1] / "tests" / "fixtures" / "same_as_examples.csv"


def _observe_and_extract(session: object, company_id: object, host: str) -> object | None:
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
    if not snapshots:
        return None
    return DomainFeatureView.from_snapshot(snapshots[-1], host)


def main() -> None:
    settings = get_settings()
    factory = create_session_factory(create_engine_from_settings(settings))
    matcher = OrganizationMatcher()

    with FIXTURE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    items: list[tuple[bool, MatchResult]] = []
    for index, row in enumerate(rows, start=1):
        secondary = normalize_domain(row["secondary_domain"])
        primary = normalize_domain(row["primary_domain"])
        with session_scope(factory) as session:
            company = Company(
                external_company_id=f"cpt-eval-{index}",
                name_raw=f"CPT {index}",
                name_normalized=f"cpt {index}",
            )
            session.add(company)
            session.flush()
            view_a = _observe_and_extract(session, company.id, secondary)
            view_b = _observe_and_extract(session, company.id, primary)
        if view_a is None or view_b is None:
            print(f"[{index:2}] {secondary} <-> {primary}: no observations (skipped)")
            continue
        result = matcher.match(view_a, view_b)
        items.append((True, result))
        print(
            f"[{index:2}] {secondary} <-> {primary}: "
            f"same_org={result.same_organization} conf={result.confidence} "
            f"codes={[c.value for c in result.reason_codes]}"
        )

    report = evaluate(items)
    print("\n=== CPT evaluation ===")
    print(f"evaluated pairs: {report.total}")
    print(f"TP={report.true_positives} FP={report.false_positives} FN={report.false_negatives}")
    print(f"precision={report.precision} recall={report.recall} f1={report.f1}")
    print(f"reason codes: {report.reason_code_counts}")


if __name__ == "__main__":
    main()
