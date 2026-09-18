"""PostgreSQL integration tests for Phase 6 primary-domain resolution.

Requires a real database (``DERE_TEST_DATABASE_URL``); skipped, never faked, when
none is configured. Seeds a same-org group, extracts features, resolves the
primary, and asserts persistence, evidence links, idempotency, and unresolved
handling.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.models.entities import (
    Company,
    Domain,
    DomainObservation,
    DomainState,
    PrimaryDomainDesignation,
    PrimaryDomainScore,
    PrimaryResolution,
    PrimaryResolutionEvidence,
    PrimaryResolutionStatus,
)
from domain_resolver.observation.results import (
    DnsObservation,
    HtmlSummary,
    HttpObservation,
    ObservationResult,
    RedirectHop,
)
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.results import ResolutionStatus
from domain_resolver.resolution.service import run_primary_resolution

pytestmark = pytest.mark.integration
EXTRACTOR = FeatureExtractor("feature-extractor-v1")


def _seed_company(session: object) -> object:
    company = Company(
        external_company_id=f"pri-{uuid4().hex[:8]}",
        name_raw="Pri Co",
        name_normalized="pri co",
    )
    session.add(company)  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    return company


def _seed_domain(
    session: object, company: object, host: str, *, redirect_to: str | None = None
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
    html = HtmlSummary(title=f"{final_host} home", text_excerpt="welcome", content_hash="h")
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


def test_primary_resolution_is_persisted_with_evidence(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company = _seed_company(session)
        primary_host = f"primary-{uuid4().hex[:6]}.test"
        a = _seed_domain(session, company, f"sec-{uuid4().hex[:6]}.test", redirect_to=primary_host)
        b = _seed_domain(session, company, primary_host)

        result = run_primary_resolution(
            session,
            company_id=company.id,
            domain_ids=[a.id, b.id],
            resolver=PrimaryDomainResolver(),
        )
        assert result.status is ResolutionStatus.RESOLVED
        assert result.primary_domain_id == b.id

        row = session.scalar(
            select(PrimaryResolution).where(PrimaryResolution.company_id == company.id)
        )
        assert row is not None
        assert row.status is PrimaryResolutionStatus.RESOLVED
        assert row.primary_domain_id == b.id

        scores = list(
            session.scalars(
                select(PrimaryDomainScore).where(PrimaryDomainScore.resolution_id == row.id)
            )
        )
        by_domain = {s.domain_id: s for s in scores}
        assert by_domain[b.id].designation is PrimaryDomainDesignation.PRIMARY
        assert by_domain[a.id].designation is PrimaryDomainDesignation.SECONDARY
        assert by_domain[b.id].evidence_ids  # traces to the REDIRECT evidence

        links = session.scalar(
            select(func.count())
            .select_from(PrimaryResolutionEvidence)
            .where(PrimaryResolutionEvidence.resolution_id == row.id)
        )
        assert links and links > 0


def test_primary_resolution_is_idempotent(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company = _seed_company(session)
        primary_host = f"p-{uuid4().hex[:6]}.test"
        a = _seed_domain(session, company, f"s-{uuid4().hex[:6]}.test", redirect_to=primary_host)
        b = _seed_domain(session, company, primary_host)
        resolver = PrimaryDomainResolver()
        run_primary_resolution(
            session, company_id=company.id, domain_ids=[a.id, b.id], resolver=resolver
        )
        run_primary_resolution(
            session, company_id=company.id, domain_ids=[a.id, b.id], resolver=resolver
        )
        count = session.scalar(
            select(func.count())
            .select_from(PrimaryResolution)
            .where(PrimaryResolution.company_id == company.id)
        )
        assert count == 1


def test_unresolved_group_persists_review_required(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company = _seed_company(session)
        # Two independent active sites with no directional evidence -> REVIEW.
        a = _seed_domain(session, company, f"x-{uuid4().hex[:6]}.test")
        b = _seed_domain(session, company, f"y-{uuid4().hex[:6]}.test")
        result = run_primary_resolution(
            session,
            company_id=company.id,
            domain_ids=[a.id, b.id],
            resolver=PrimaryDomainResolver(),
        )
        assert result.status is ResolutionStatus.REVIEW_REQUIRED
        row = session.scalar(
            select(PrimaryResolution).where(PrimaryResolution.company_id == company.id)
        )
        assert row is not None
        assert row.primary_domain_id is None
        scores = list(
            session.scalars(
                select(PrimaryDomainScore).where(PrimaryDomainScore.resolution_id == row.id)
            )
        )
        assert all(s.designation is PrimaryDomainDesignation.UNRESOLVED for s in scores)
