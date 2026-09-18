"""Phase 6 primary-domain resolution routes.

Given a same-organization group of domains, returns the explainable
primary/secondary resolution. Performs no crawling/DNS/LLM and selects no final
CPT decision (that is Phase 7).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.dependencies import primary_resolver_dependency, session_dependency
from domain_resolver.models.entities import PrimaryResolution as PrimaryResolutionRow
from domain_resolver.repositories.sqlalchemy import SqlAlchemyPrimaryResolutionRepository
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.results import PrimaryResolution
from domain_resolver.resolution.service import run_primary_resolution

router = APIRouter(tags=["primary-resolution"])


class ResolvePrimaryRequest(BaseModel):
    """A set of domains already confirmed (by Phase 5) to be the same organization."""

    domain_ids: list[UUID] = Field(min_length=1)


class PrimaryResolutionRowResponse(BaseModel):
    id: UUID
    company_id: UUID
    status: str
    primary_domain_id: UUID | None
    confidence: float | None
    confidence_band: str | None
    margin: float | None
    domain_ids: list[Any]
    conflicts: list[Any] | None
    created_at: datetime

    @classmethod
    def from_model(cls, row: PrimaryResolutionRow) -> PrimaryResolutionRowResponse:
        return cls(
            id=row.id,
            company_id=row.company_id,
            status=row.status.value,
            primary_domain_id=row.primary_domain_id,
            confidence=row.confidence,
            confidence_band=row.confidence_band,
            margin=row.margin,
            domain_ids=row.domain_ids,
            conflicts=row.conflicts,
            created_at=row.created_at,
        )


@router.post("/companies/{company_id}/resolve-primary", response_model=PrimaryResolution)
def resolve_primary(
    company_id: UUID,
    request: ResolvePrimaryRequest,
    session: Annotated[Session, Depends(session_dependency)],
    resolver: Annotated[PrimaryDomainResolver, Depends(primary_resolver_dependency)],
) -> PrimaryResolution:
    return run_primary_resolution(
        session, company_id=company_id, domain_ids=request.domain_ids, resolver=resolver
    )


@router.get(
    "/companies/{company_id}/primary-resolutions",
    response_model=list[PrimaryResolutionRowResponse],
)
def list_primary_resolutions(
    company_id: UUID,
    session: Annotated[Session, Depends(session_dependency)],
) -> list[PrimaryResolutionRowResponse]:
    rows = SqlAlchemyPrimaryResolutionRepository(session).list_by_company(company_id)
    return [PrimaryResolutionRowResponse.from_model(row) for row in rows]
