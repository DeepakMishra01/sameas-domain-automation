"""Celery task wrapping the safe domain observation service.

The task is idempotent (keyed by ``idempotency_key`` via ``crawl_jobs``),
retryable (transient failures raise and Celery retries), bounded (all limits live
in the observation layer), and observable (structured logs + job lifecycle).
A failure for one domain raises only for that task and never affects others.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from apps.worker.celery_app import celery_app
from domain_resolver.config.settings import get_settings
from domain_resolver.infrastructure.database import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)
from domain_resolver.observation.dns_observer import DnsObserver
from domain_resolver.observation.http_observer import HttpObserver
from domain_resolver.observation.service import run_domain_observation


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="dere.observe_domain",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def observe_domain(
    self: object,
    company_id: str,
    domain_id: str,
    idempotency_key: str | None = None,
) -> str:
    """Observe a single candidate domain and return the observation id."""
    settings = get_settings()
    session_factory = create_session_factory(create_engine_from_settings(settings))
    key = idempotency_key or uuid4().hex
    with session_scope(session_factory) as session:
        observation = run_domain_observation(
            session,
            company_id=UUID(company_id),
            domain_id=UUID(domain_id),
            idempotency_key=key,
            collector_version=settings.collector_version,
            dns_observer=DnsObserver(),
            http_observer=HttpObserver(),
        )
        return str(observation.id)
