"""Observation orchestration: run observers, persist facts, link evidence.

This service is broker-independent so it can be driven from the API synchronously
or from a Celery task. It is idempotent per ``idempotency_key`` (backed by
``crawl_jobs``), preserves history (every distinct run appends a new
``domain_observations`` row), and records only factual evidence traceable to its
observation. It performs no matching, scoring, or primary-domain logic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from domain_resolver.models.base import utc_now
from domain_resolver.models.entities import (
    CrawlJob,
    CrawlJobStatus,
    DomainObservation,
    DomainState,
    Evidence,
)
from domain_resolver.observation.logging import log_event, log_failure
from domain_resolver.observation.results import DnsObservation, HttpObservation, ObservationResult
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyCrawlJobRepository,
    SqlAlchemyDomainObservationRepository,
    SqlAlchemyDomainRepository,
    SqlAlchemyEvidenceRepository,
)


class DnsObserverPort(Protocol):
    def observe(self, hostname: str) -> DnsObservation: ...


class HttpObserverPort(Protocol):
    def observe(self, hostname: str) -> HttpObservation: ...


class DomainNotFoundError(Exception):
    """Raised when the requested domain does not exist."""


def run_domain_observation(
    session: Session,
    *,
    company_id: UUID,
    domain_id: UUID,
    idempotency_key: str,
    collector_version: str,
    dns_observer: DnsObserverPort,
    http_observer: HttpObserverPort,
    now: Callable[[], datetime] = utc_now,
) -> DomainObservation:
    """Observe one candidate domain and persist the factual result.

    Returns the persisted :class:`DomainObservation`. Re-running with an
    ``idempotency_key`` whose job already succeeded returns the existing
    observation without producing a duplicate.
    """
    jobs = SqlAlchemyCrawlJobRepository(session)
    domains = SqlAlchemyDomainRepository(session)
    observations = SqlAlchemyDomainObservationRepository(session)
    evidence_repo = SqlAlchemyEvidenceRepository(session)

    existing_job = jobs.get_by_idempotency_key(idempotency_key)
    if existing_job is not None and existing_job.status is CrawlJobStatus.SUCCEEDED:
        payload = existing_job.result_payload or {}
        observation_id = payload.get("observation_id")
        if observation_id is not None:
            existing = observations.get_by_id(UUID(str(observation_id)))
            if existing is not None:
                log_event(
                    "observation_idempotent_hit",
                    company_id=company_id,
                    domain_id=domain_id,
                    observation_id=existing.id,
                    job_id=existing_job.id,
                    collector_version=collector_version,
                )
                return existing

    domain = domains.get_by_id(domain_id)
    if domain is None:
        raise DomainNotFoundError(f"domain {domain_id} does not exist")

    job = existing_job or jobs.create(
        CrawlJob(
            domain_id=domain_id,
            correlation_id=idempotency_key[:128],
            idempotency_key=idempotency_key,
            status=CrawlJobStatus.PENDING,
        )
    )
    job.status = CrawlJobStatus.RUNNING
    job.started_at = now()
    jobs.save(job)

    log_event(
        "observation_started",
        company_id=company_id,
        domain_id=domain_id,
        job_id=job.id,
        hostname=domain.hostname,
        collector_version=collector_version,
    )

    try:
        dns_observation = dns_observer.observe(domain.hostname)
        log_event(
            "dns_attempt",
            domain_id=domain_id,
            job_id=job.id,
            error_category=dns_observation.error_category,
        )
        http_observation = http_observer.observe(domain.hostname)
        log_event(
            "http_attempt",
            domain_id=domain_id,
            job_id=job.id,
            status=http_observation.status_code,
            redirects=len(http_observation.redirect_chain),
            error_category=http_observation.error_category,
        )
    except Exception as exc:  # noqa: BLE001 - record job failure, allow retry/isolation
        job.status = CrawlJobStatus.FAILED
        job.completed_at = now()
        job.result_payload = {"error": f"{type(exc).__name__}: {exc}"}
        jobs.save(job)
        log_failure(
            "observation_failed",
            company_id=company_id,
            domain_id=domain_id,
            job_id=job.id,
            error=type(exc).__name__,
        )
        raise

    observed_at = now()
    result = ObservationResult(
        collector_version=collector_version,
        observed_at=observed_at,
        dns=dns_observation,
        http=http_observation,
    )
    error_detail = http_observation.error_detail or dns_observation.error_detail

    observation = observations.create(
        DomainObservation(
            company_id=company_id,
            domain_id=domain_id,
            source=collector_version,
            raw_domain=domain.hostname,
            state=DomainState.UNKNOWN,
            collector_version=collector_version,
            error_category=result.error_category,
            error_detail=error_detail,
            observed_at=observed_at,
            payload=result.model_dump(mode="json"),
        )
    )

    _record_factual_evidence(
        evidence_repo,
        observation=observation,
        domain_id=domain_id,
        collector_version=collector_version,
        http_observation=http_observation,
        observed_at=observed_at,
    )

    job.status = CrawlJobStatus.SUCCEEDED
    job.completed_at = now()
    job.result_payload = {
        "observation_id": str(observation.id),
        "error_category": result.error_category,
    }
    jobs.save(job)

    log_event(
        "observation_completed",
        company_id=company_id,
        domain_id=domain_id,
        observation_id=observation.id,
        job_id=job.id,
        collector_version=collector_version,
        error_category=result.error_category,
    )
    return observation


def _record_factual_evidence(
    evidence_repo: SqlAlchemyEvidenceRepository,
    *,
    observation: DomainObservation,
    domain_id: UUID,
    collector_version: str,
    http_observation: HttpObservation,
    observed_at: datetime,
) -> None:
    """Create factual, traceable evidence from an observation.

    Only observable facts are recorded (a redirect happened; a canonical URL was
    declared). No SAME_ORGANIZATION / PRIMARY_DOMAIN interpretation is produced.
    """
    if http_observation.redirect_chain:
        evidence_repo.create(
            Evidence(
                reason_code="REDIRECT",
                evidence_type="HTTP_REDIRECT",
                source=collector_version,
                domain_a_id=domain_id,
                value=None,
                strength=None,
                observation_id=observation.id,
                observed_at=observed_at,
                raw_payload={
                    "chain": [hop.model_dump() for hop in http_observation.redirect_chain],
                    "final_url": http_observation.final_url,
                    "final_hostname": http_observation.final_hostname,
                },
            )
        )

    html = http_observation.html
    if html is not None and html.canonical_url:
        evidence_repo.create(
            Evidence(
                reason_code="CANONICAL_URL",
                evidence_type="HTML_CANONICAL",
                source=collector_version,
                domain_a_id=domain_id,
                value=None,
                strength=None,
                observation_id=observation.id,
                observed_at=observed_at,
                raw_payload={
                    "canonical_url": html.canonical_url,
                    "source_url": http_observation.final_url,
                },
            )
        )
