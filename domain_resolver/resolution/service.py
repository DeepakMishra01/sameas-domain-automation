"""Primary-domain resolution orchestration and persistence.

Consumes stored Phase 4 features only (no network/DNS/LLM). Given a company and a
set of domains already confirmed same-organization, it resolves the primary
domain, persists the result (separate from the final CPT ``decisions`` table),
and links the supporting Phase 4 evidence. Idempotent per company + group +
resolver version.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.models.base import utc_now
from domain_resolver.models.entities import (
    Evidence,
    ModelVersion,
    ModelVersionKind,
    PrimaryDomainDesignation,
    PrimaryDomainScore,
    PrimaryResolution,
    PrimaryResolutionEvidence,
    PrimaryResolutionStatus,
)
from domain_resolver.observation.logging import log_event
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyDomainRepository,
    SqlAlchemyModelVersionRepository,
    SqlAlchemyObservationFeatureRepository,
    SqlAlchemyPrimaryResolutionRepository,
)
from domain_resolver.resolution.provenance import PRIMARY_CODE_TO_EVIDENCE
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.results import DomainScore
from domain_resolver.resolution.results import PrimaryResolution as PrimaryResolutionResult
from domain_resolver.resolution.signals import GroupSignals, compute_group_signals


def run_primary_resolution(
    session: Session,
    *,
    company_id: UUID,
    domain_ids: list[UUID],
    resolver: PrimaryDomainResolver,
    now: Callable[[], datetime] = utc_now,
) -> PrimaryResolutionResult:
    """Resolve the primary domain for a same-org group and persist it idempotently."""
    domains = SqlAlchemyDomainRepository(session)
    features = SqlAlchemyObservationFeatureRepository(session)

    views: list[DomainFeatureView] = []
    for domain_id in domain_ids:
        domain = domains.get_by_id(domain_id)
        if domain is None:
            continue
        snapshots = features.list_by_domain(domain_id)
        if not snapshots:
            continue
        views.append(DomainFeatureView.from_snapshot(snapshots[-1], domain.hostname))

    resolution = resolver.resolve(views)  # deterministic pydantic result
    model_version = _ensure_model_version(session, resolver)
    group_key = _group_key([view.domain_id for view in views])
    resolutions = SqlAlchemyPrimaryResolutionRepository(session)

    log_event(
        "primary_resolution_started",
        company_id=company_id,
        domains=len(views),
        resolver_version=resolver.version,
    )

    existing = resolutions.get_by_company_group_version(company_id, group_key, model_version.id)
    if existing is not None:
        log_event(
            "primary_resolution_idempotent_hit",
            company_id=company_id,
            resolution_id=existing.id,
            resolver_version=resolver.version,
        )
        return resolution

    group_signals = compute_group_signals(views)
    row = resolutions.create(
        PrimaryResolution(
            company_id=company_id,
            group_key=group_key,
            model_version_id=model_version.id,
            status=PrimaryResolutionStatus(resolution.status.value),
            primary_domain_id=resolution.primary_domain_id,
            confidence=resolution.confidence,
            confidence_band=resolution.confidence_band.value,
            margin=resolution.margin,
            domain_ids=[str(view.domain_id) for view in views],
            conflicts=resolution.conflicts or None,
        )
    )

    all_evidence: set[UUID] = set()
    for score in resolution.scores:
        evidence_ids = _evidence_for_score(session, score, group_signals)
        all_evidence |= set(evidence_ids)
        session.add(
            PrimaryDomainScore(
                resolution_id=row.id,
                domain_id=score.domain_id,
                primary_score=score.primary_score,
                designation=PrimaryDomainDesignation(score.designation.value),
                reason_codes=[code.value for code in score.reason_codes],
                evidence_ids=[str(evidence_id) for evidence_id in evidence_ids],
            )
        )
    for evidence_id in all_evidence:
        session.add(PrimaryResolutionEvidence(resolution_id=row.id, evidence_id=evidence_id))
    session.flush()

    log_event(
        "primary_resolution_completed",
        company_id=company_id,
        resolution_id=row.id,
        status=resolution.status.value,
        primary_host=resolution.primary_host,
        resolver_version=resolver.version,
    )
    return resolution


def _ensure_model_version(session: Session, resolver: PrimaryDomainResolver) -> ModelVersion:
    versions = SqlAlchemyModelVersionRepository(session)
    existing = versions.get_by_version(resolver.version)
    if existing is not None:
        return existing
    return versions.create(
        ModelVersion(
            version=resolver.version,
            kind=ModelVersionKind.RULES,
            configuration=resolver.config.to_configuration(),
        )
    )


def _group_key(domain_ids: list[UUID]) -> str:
    joined = ",".join(sorted(str(domain_id) for domain_id in domain_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _evidence_for_score(
    session: Session, score: DomainScore, group_signals: GroupSignals
) -> list[UUID]:
    signals = group_signals.signals.get(score.domain_id)
    if signals is None:
        return []
    collected: set[UUID] = set()
    for code in score.reason_codes:
        evidence_codes = PRIMARY_CODE_TO_EVIDENCE.get(code)
        if not evidence_codes:
            continue
        for source in signals.positive.get(code, []):
            ids = session.scalars(
                select(Evidence.id).where(
                    Evidence.observation_id == source.observation_id,
                    Evidence.reason_code.in_(evidence_codes),
                )
            )
            collected.update(ids)
    return sorted(collected, key=str)
