"""PostgreSQL integration tests for Phase 5 organization matching.

Requires a real database (``DERE_TEST_DATABASE_URL``); skipped, never faked, when
none is configured. Seeds observations, runs the real Phase 4 extraction, then
Phase 5 matching, exercising the full match -> evidence -> observation chain.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.matching.service import run_organization_matching
from domain_resolver.models.entities import (
    Company,
    Domain,
    DomainObservation,
    DomainRelationship,
    DomainState,
)
from domain_resolver.observation.results import (
    DnsObservation,
    HtmlSummary,
    HttpObservation,
    ObservationResult,
    RedirectHop,
)
from domain_resolver.repositories.sqlalchemy import SqlAlchemyRelationshipEvidenceRepository

pytestmark = pytest.mark.integration
EXTRACTOR = FeatureExtractor("feature-extractor-v1")


def _seed_company(session: object) -> object:
    company = Company(
        external_company_id=f"match-{uuid4().hex[:8]}",
        name_raw="Match Co",
        name_normalized="match co",
    )
    session.add(company)  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    return company


def _seed_domain(
    session: object,
    company: object,
    host: str,
    *,
    redirect_to: str | None = None,
    email: str = "info@corp.test",
) -> object:
    domain = Domain(hostname=host)
    session.add(domain)  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    final_host = redirect_to or host
    chain = (
        [
            RedirectHop(
                source_url=f"https://{host}/",
                status_code=301,
                location=f"https://{redirect_to}/",
                target_url=f"https://{redirect_to}/",
            )
        ]
        if redirect_to
        else []
    )
    html = HtmlSummary(title=f"{host}", links=[f"mailto:{email}"], content_hash="h")
    http = HttpObservation(
        requested_url=f"https://{host}/",
        status_code=200,
        content_type="text/html",
        final_url=f"https://{final_host}/",
        final_hostname=final_host,
        redirect_chain=chain,
        html=html,
    )
    payload = ObservationResult(
        collector_version="c",
        observed_at=datetime.now(UTC),
        dns=DnsObservation(hostname=host),
        http=http,
    ).model_dump(mode="json")
    observation = DomainObservation(
        company_id=company.id,
        domain_id=domain.id,
        raw_domain=host,
        state=DomainState.UNKNOWN,
        collector_version="c",
        payload=payload,
    )
    session.add(observation)  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    run_feature_extraction(session, observation_id=observation.id, extractor=EXTRACTOR)  # type: ignore[arg-type]
    return domain


def test_match_is_persisted_with_evidence_links(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company = _seed_company(session)
        host_b = f"b-{uuid4().hex[:8]}.test"
        host_a = f"a-{uuid4().hex[:8]}.test"
        a = _seed_domain(session, company, host_a, redirect_to=host_b)
        b = _seed_domain(session, company, host_b)

        report = run_organization_matching(
            session, company_id=company.id, domain_ids=[a.id, b.id], matcher=OrganizationMatcher()
        )
        assert report.results
        match = report.results[0]
        assert match.same_organization is True
        assert "REDIRECT" in [c.value for c in match.reason_codes]

        low, high = (a.id, b.id) if a.id < b.id else (b.id, a.id)
        rel = session.scalar(
            select(DomainRelationship).where(
                DomainRelationship.company_id == company.id,
                DomainRelationship.domain_a_id == low,
                DomainRelationship.domain_b_id == high,
            )
        )
        assert rel is not None
        assert rel.same_organization is True
        assert rel.reason_codes and "REDIRECT" in rel.reason_codes

        linked = SqlAlchemyRelationshipEvidenceRepository(session).list_evidence_for_relationship(
            rel.id
        )
        assert linked  # match traces to concrete Phase 4 evidence rows
        assert all(row.observation_id is not None for row in linked)


def test_matching_is_idempotent(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company = _seed_company(session)
        host_b = f"b-{uuid4().hex[:8]}.test"
        a = _seed_domain(session, company, f"a-{uuid4().hex[:8]}.test", redirect_to=host_b)
        b = _seed_domain(session, company, host_b)
        matcher = OrganizationMatcher()

        run_organization_matching(
            session, company_id=company.id, domain_ids=[a.id, b.id], matcher=matcher
        )
        count_after_first = session.scalar(
            select(func.count())
            .select_from(DomainRelationship)
            .where(DomainRelationship.company_id == company.id)
        )
        run_organization_matching(
            session, company_id=company.id, domain_ids=[a.id, b.id], matcher=matcher
        )
        count_after_second = session.scalar(
            select(func.count())
            .select_from(DomainRelationship)
            .where(DomainRelationship.company_id == company.id)
        )
        assert count_after_first == count_after_second


def test_multiple_domains_form_one_group(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company = _seed_company(session)
        # Three domains sharing a corporate email domain -> one organization group.
        shared = f"corp-{uuid4().hex[:6]}.test"
        a = _seed_domain(session, company, f"a-{uuid4().hex[:8]}.test", email=f"info@{shared}")
        b = _seed_domain(session, company, f"b-{uuid4().hex[:8]}.test", email=f"info@{shared}")
        c = _seed_domain(session, company, f"c-{uuid4().hex[:8]}.test", email=f"info@{shared}")

        report = run_organization_matching(
            session,
            company_id=company.id,
            domain_ids=[a.id, b.id, c.id],
            matcher=OrganizationMatcher(),
        )
        big = max(report.groups, key=lambda g: len(g.domain_ids))
        assert set(big.domain_ids) == {a.id, b.id, c.id}
