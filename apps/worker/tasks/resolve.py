"""Celery task wrapping deterministic primary-domain resolution.

Consumes stored features only (no network/DNS/LLM). Idempotent per company +
group + resolver version. A failure for one group raises only for that task.
"""

from __future__ import annotations

from uuid import UUID

from apps.worker.celery_app import celery_app
from domain_resolver.config.settings import get_settings
from domain_resolver.infrastructure.database import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)
from domain_resolver.resolution.config import ResolverConfig
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.service import run_primary_resolution


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="dere.resolve_primary",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def resolve_primary(self: object, company_id: str, domain_ids: list[str]) -> str:
    """Resolve the primary domain for a same-org group; returns the status."""
    settings = get_settings()
    session_factory = create_session_factory(create_engine_from_settings(settings))
    resolver = PrimaryDomainResolver(ResolverConfig(version=settings.resolver_version))
    with session_scope(session_factory) as session:
        resolution = run_primary_resolution(
            session,
            company_id=UUID(company_id),
            domain_ids=[UUID(value) for value in domain_ids],
            resolver=resolver,
        )
        return resolution.status.value
