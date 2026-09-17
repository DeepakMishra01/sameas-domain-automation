"""Organization-matching orchestration and persistence.

Consumes already-collected Phase 4 features only — it never crawls, resolves
DNS, or calls the network/LLM. It generates candidate pairs, runs the
deterministic matcher, groups domains, and persists each assessment as a
``DomainRelationship`` (canonical pair, idempotent per company+pair+version) with
``RelationshipEvidence`` links back to the supporting Phase 4 evidence rows.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from domain_resolver.matching.candidates import generate_candidate_pairs
from domain_resolver.matching.grouping import OrganizationGroup, group_domains
from domain_resolver.matching.matcher import MatchResult, OrganizationMatcher
from domain_resolver.matching.provenance import MATCH_CODE_TO_EVIDENCE_CODES
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.models.base import utc_now
from domain_resolver.models.entities import (
    DomainRelationship,
    Evidence,
    ModelVersion,
    ModelVersionKind,
    RelationshipState,
)
from domain_resolver.observation.logging import log_event
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyDomainRelationshipRepository,
    SqlAlchemyDomainRepository,
    SqlAlchemyModelVersionRepository,
    SqlAlchemyObservationFeatureRepository,
    SqlAlchemyRelationshipEvidenceRepository,
)


class MatchingReport(BaseModel):
    results: list[MatchResult] = Field(default_factory=list)
    groups: list[OrganizationGroup] = Field(default_factory=list)


def run_matching(views: list[DomainFeatureView], matcher: OrganizationMatcher) -> MatchingReport:
    """Pure pipeline: candidate generation -> pairwise matching -> grouping."""
    results = [
        matcher.match(view_a, view_b)
        for view_a, view_b in generate_candidate_pairs(views, matcher.config)
    ]
    return MatchingReport(results=results, groups=group_domains(results))


def run_organization_matching(
    session: Session,
    *,
    company_id: UUID,
    domain_ids: list[UUID],
    matcher: OrganizationMatcher,
    now: Callable[[], datetime] = utc_now,
) -> MatchingReport:
    """Load features for the domains, match, and persist assessments idempotently."""
    domains = SqlAlchemyDomainRepository(session)
    features = SqlAlchemyObservationFeatureRepository(session)

    views: list[DomainFeatureView] = []
    for domain_id in domain_ids:
        domain = domains.get_by_id(domain_id)
        if domain is None:
            continue
        snapshots = features.list_by_domain(domain_id)
        if not snapshots:
            continue  # no features yet; cannot match this domain
        views.append(DomainFeatureView.from_snapshot(snapshots[-1], domain.hostname))

    log_event(
        "organization_matching_started",
        company_id=company_id,
        domains=len(views),
        matcher_version=matcher.version,
    )

    report = run_matching(views, matcher)
    model_version = _ensure_model_version(session, matcher)
    for result in report.results:
        _persist_assessment(session, company_id, model_version, result, now)

    log_event(
        "organization_matching_completed",
        company_id=company_id,
        pairs=len(report.results),
        groups=len(report.groups),
        matcher_version=matcher.version,
    )
    return report


def _ensure_model_version(session: Session, matcher: OrganizationMatcher) -> ModelVersion:
    versions = SqlAlchemyModelVersionRepository(session)
    existing = versions.get_by_version(matcher.version)
    if existing is not None:
        return existing
    return versions.create(
        ModelVersion(
            version=matcher.version,
            kind=ModelVersionKind.RULES,
            configuration=matcher.config.to_configuration(),
        )
    )


def _persist_assessment(
    session: Session,
    company_id: UUID,
    model_version: ModelVersion,
    result: MatchResult,
    now: Callable[[], datetime],
) -> None:
    relationships = SqlAlchemyDomainRelationshipRepository(session)
    existing = relationships.get_by_company_pair_and_version(
        company_id, result.domain_a_id, result.domain_b_id, model_version.id
    )
    if existing is not None:
        return  # idempotent: this pair was already assessed by this matcher version

    relationship = relationships.create(
        DomainRelationship(
            company_id=company_id,
            domain_a_id=result.domain_a_id,
            domain_b_id=result.domain_b_id,
            same_organization=result.same_organization,
            state=(
                RelationshipState.SAME_ORGANIZATION
                if result.same_organization
                else RelationshipState.UNKNOWN
            ),
            confidence=result.confidence,
            reason_codes=[code.value for code in result.reason_codes],
            match_features={
                "confidence_band": result.confidence_band.value,
                "negative_reason_codes": [c.value for c in result.negative_reason_codes],
                **result.features,
            },
            model_version_id=model_version.id,
            assessed_at=now(),
        )
    )
    _link_evidence(session, relationship.id, result)


def _link_evidence(session: Session, relationship_id: UUID, result: MatchResult) -> None:
    evidence_codes: set[str] = set()
    for code in result.reason_codes:
        evidence_codes.update(MATCH_CODE_TO_EVIDENCE_CODES.get(code, frozenset()))
    if not evidence_codes:
        return

    evidence_ids = list(
        session.scalars(
            select(Evidence.id).where(
                Evidence.domain_a_id.in_([result.domain_a_id, result.domain_b_id]),
                Evidence.reason_code.in_(evidence_codes),
            )
        )
    )
    links = SqlAlchemyRelationshipEvidenceRepository(session)
    for evidence_id in evidence_ids:
        links.link(relationship_id, evidence_id)
