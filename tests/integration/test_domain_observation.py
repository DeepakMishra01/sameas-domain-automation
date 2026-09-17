"""PostgreSQL integration tests for the observation service (Phase 3).

These require a real database (``DERE_TEST_DATABASE_URL``); they are skipped, not
substituted with SQLite, when none is configured. Observers are faked so no real
network or DNS is used — the focus is persistence, history, idempotency,
evidence traceability, and job lifecycle.
"""

from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.models.entities import (
    Company,
    CrawlJob,
    CrawlJobStatus,
    Domain,
    DomainObservation,
    Evidence,
)
from domain_resolver.observation.results import (
    DnsObservation,
    DnsRecordSet,
    HtmlSummary,
    HttpObservation,
    RedirectHop,
)
from domain_resolver.observation.service import DomainNotFoundError, run_domain_observation

pytestmark = pytest.mark.integration

COLLECTOR = "domain-observer-test"


class FakeDnsObserver:
    def observe(self, hostname: str) -> DnsObservation:
        return DnsObservation(
            hostname=hostname,
            records=[DnsRecordSet(record_type="A", values=["93.184.216.34"])],
        )


class FakeHttpObserver:
    def __init__(self, observation: HttpObservation) -> None:
        self._observation = observation

    def observe(self, hostname: str) -> HttpObservation:
        return self._observation


def _plain_http() -> HttpObservation:
    return HttpObservation(
        requested_url="https://example.test/",
        scheme_attempts=["https"],
        status_code=200,
        content_type="text/html",
        final_url="https://example.test/",
        final_hostname="example.test",
    )


def _redirect_http() -> HttpObservation:
    return HttpObservation(
        requested_url="https://example.test/",
        scheme_attempts=["https"],
        status_code=200,
        content_type="text/html",
        redirect_chain=[
            RedirectHop(
                source_url="https://example.test/",
                status_code=301,
                location="https://www.example.test/",
                target_url="https://www.example.test/",
            )
        ],
        final_url="https://www.example.test/",
        final_hostname="www.example.test",
        html=HtmlSummary(
            title="Example", canonical_url="https://www.example.test/", content_hash="h"
        ),
    )


def _seed(session: object) -> tuple[object, object]:
    company = Company(
        external_company_id=f"obs-{uuid4().hex[:8]}",
        name_raw="Obs Co",
        name_normalized="obs co",
    )
    domain = Domain(hostname=f"{uuid4().hex[:8]}.example.test")
    session.add_all([company, domain])  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    return company, domain


def test_observation_is_persisted(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company, domain = _seed(session)
        observation = run_domain_observation(
            session,
            company_id=company.id,
            domain_id=domain.id,
            idempotency_key=uuid4().hex,
            collector_version=COLLECTOR,
            dns_observer=FakeDnsObserver(),
            http_observer=FakeHttpObserver(_plain_http()),
        )
        assert observation.collector_version == COLLECTOR
        assert observation.error_category is None
        assert observation.payload is not None
        assert observation.payload["http"]["status_code"] == 200
        assert observation.payload["dns"]["records"][0]["values"] == ["93.184.216.34"]


def test_history_is_appended_across_distinct_runs(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company, domain = _seed(session)
        domain_id = domain.id
        for _ in range(2):
            run_domain_observation(
                session,
                company_id=company.id,
                domain_id=domain_id,
                idempotency_key=uuid4().hex,
                collector_version=COLLECTOR,
                dns_observer=FakeDnsObserver(),
                http_observer=FakeHttpObserver(_plain_http()),
            )
        count = session.scalar(
            select(func.count())
            .select_from(DomainObservation)
            .where(DomainObservation.domain_id == domain_id)
        )
        assert count == 2


def test_idempotent_rerun_does_not_duplicate(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    key = uuid4().hex
    with session_scope(factory) as session:
        company, domain = _seed(session)
        domain_id = domain.id
        first = run_domain_observation(
            session,
            company_id=company.id,
            domain_id=domain_id,
            idempotency_key=key,
            collector_version=COLLECTOR,
            dns_observer=FakeDnsObserver(),
            http_observer=FakeHttpObserver(_plain_http()),
        )
        first_id = first.id

    with session_scope(factory) as session:
        second = run_domain_observation(
            session,
            company_id=first.company_id,
            domain_id=domain_id,
            idempotency_key=key,
            collector_version=COLLECTOR,
            dns_observer=FakeDnsObserver(),
            http_observer=FakeHttpObserver(_plain_http()),
        )
        assert second.id == first_id

    with session_scope(factory) as session:
        count = session.scalar(
            select(func.count())
            .select_from(DomainObservation)
            .where(DomainObservation.domain_id == domain_id)
        )
        assert count == 1
        jobs = list(session.scalars(select(CrawlJob).where(CrawlJob.idempotency_key == key)))
        assert len(jobs) == 1
        assert jobs[0].status is CrawlJobStatus.SUCCEEDED


def test_factual_evidence_is_linked_to_observation(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company, domain = _seed(session)
        observation = run_domain_observation(
            session,
            company_id=company.id,
            domain_id=domain.id,
            idempotency_key=uuid4().hex,
            collector_version=COLLECTOR,
            dns_observer=FakeDnsObserver(),
            http_observer=FakeHttpObserver(_redirect_http()),
        )
        evidence = list(
            session.scalars(select(Evidence).where(Evidence.observation_id == observation.id))
        )
        reason_codes = {row.reason_code for row in evidence}
        assert reason_codes == {"REDIRECT", "CANONICAL_URL"}
        for row in evidence:
            assert row.observation_id == observation.id
            assert row.domain_a_id == domain.id
            assert row.strength is None  # factual evidence asserts no weight


def test_job_lifecycle_is_recorded(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    key = uuid4().hex
    with session_scope(factory) as session:
        company, domain = _seed(session)
        observation = run_domain_observation(
            session,
            company_id=company.id,
            domain_id=domain.id,
            idempotency_key=key,
            collector_version=COLLECTOR,
            dns_observer=FakeDnsObserver(),
            http_observer=FakeHttpObserver(_plain_http()),
        )
        job = session.scalar(select(CrawlJob).where(CrawlJob.idempotency_key == key))
        assert job is not None
        assert job.status is CrawlJobStatus.SUCCEEDED
        assert job.started_at is not None
        assert job.completed_at is not None
        assert job.result_payload is not None
        assert job.result_payload["observation_id"] == str(observation.id)


def test_missing_domain_raises(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        company, _ = _seed(session)
        with pytest.raises(DomainNotFoundError):
            run_domain_observation(
                session,
                company_id=company.id,
                domain_id=uuid4(),
                idempotency_key=uuid4().hex,
                collector_version=COLLECTOR,
                dns_observer=FakeDnsObserver(),
                http_observer=FakeHttpObserver(_plain_http()),
            )
