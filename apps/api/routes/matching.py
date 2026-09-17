"""Phase 5 organization-matching routes.

Runs the deterministic matcher over already-collected features and returns
explainable same-organization results. It performs no crawling, DNS, LLM, or
primary-domain selection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.dependencies import organization_matcher_dependency, session_dependency
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.matching.service import MatchingReport, run_organization_matching
from domain_resolver.models.entities import DomainRelationship
from domain_resolver.repositories.sqlalchemy import SqlAlchemyDomainRelationshipRepository

router = APIRouter(tags=["matching"])


class MatchRequest(BaseModel):
    domain_ids: list[UUID] = Field(min_length=1)


class RelationshipResponse(BaseModel):
    id: UUID
    company_id: UUID
    domain_a_id: UUID
    domain_b_id: UUID
    same_organization: bool | None
    state: str
    confidence: float | None
    reason_codes: list[Any] | None
    match_features: dict[str, Any] | None
    model_version_id: UUID
    assessed_at: datetime

    @classmethod
    def from_model(cls, relationship: DomainRelationship) -> RelationshipResponse:
        return cls(
            id=relationship.id,
            company_id=relationship.company_id,
            domain_a_id=relationship.domain_a_id,
            domain_b_id=relationship.domain_b_id,
            same_organization=relationship.same_organization,
            state=relationship.state.value,
            confidence=relationship.confidence,
            reason_codes=relationship.reason_codes,
            match_features=relationship.match_features,
            model_version_id=relationship.model_version_id,
            assessed_at=relationship.assessed_at,
        )


@router.post("/companies/{company_id}/match", response_model=MatchingReport)
def match_company(
    company_id: UUID,
    request: MatchRequest,
    session: Annotated[Session, Depends(session_dependency)],
    matcher: Annotated[OrganizationMatcher, Depends(organization_matcher_dependency)],
) -> MatchingReport:
    return run_organization_matching(
        session, company_id=company_id, domain_ids=request.domain_ids, matcher=matcher
    )


@router.get(
    "/companies/{company_id}/relationships",
    response_model=list[RelationshipResponse],
)
def list_company_relationships(
    company_id: UUID,
    session: Annotated[Session, Depends(session_dependency)],
) -> list[RelationshipResponse]:
    relationships = SqlAlchemyDomainRelationshipRepository(session).list_by_company(company_id)
    return [RelationshipResponse.from_model(item) for item in relationships]
