"""Celery task wrapping deterministic organization matching.

Consumes already-collected features only (no network/DNS/LLM). Idempotent per
company + pair + matcher version. A failure for one company raises only for that
task.
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
from domain_resolver.matching.config import MatcherConfig
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.matching.service import run_organization_matching


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="dere.match_company",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def match_company(self: object, company_id: str, domain_ids: list[str]) -> int:
    """Match a company's candidate domains; returns the number of assessed pairs."""
    settings = get_settings()
    session_factory = create_session_factory(create_engine_from_settings(settings))
    matcher = OrganizationMatcher(MatcherConfig(version=settings.matcher_version))
    with session_scope(session_factory) as session:
        report = run_organization_matching(
            session,
            company_id=UUID(company_id),
            domain_ids=[UUID(value) for value in domain_ids],
            matcher=matcher,
        )
        return len(report.results)
