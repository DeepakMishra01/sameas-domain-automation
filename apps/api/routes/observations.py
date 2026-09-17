"""Domain observation routes: trigger and query factual observations.

These endpoints deliberately expose observation only. No matching, resolution,
or decision endpoint exists in Phase 3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.dependencies import (
    dns_observer_dependency,
    http_observer_dependency,
    session_dependency,
    settings_dependency,
)
from domain_resolver.config.settings import Settings
from domain_resolver.models.entities import DomainObservation, ObservationErrorCategory
from domain_resolver.observation.service import (
    DnsObserverPort,
    DomainNotFoundError,
    HttpObserverPort,
    run_domain_observation,
)
from domain_resolver.repositories.sqlalchemy import SqlAlchemyDomainObservationRepository

router = APIRouter(tags=["observations"])


class ObserveRequest(BaseModel):
    """Request to observe a candidate domain already supplied by CPT."""

    company_id: UUID
    idempotency_key: str | None = Field(default=None, max_length=256)


class ObservationResponse(BaseModel):
    id: UUID
    company_id: UUID
    domain_id: UUID
    collector_version: str | None
    error_category: ObservationErrorCategory | None
    error_detail: str | None
    observed_at: datetime
    payload: dict[str, Any] | None

    @classmethod
    def from_model(cls, observation: DomainObservation) -> ObservationResponse:
        return cls(
            id=observation.id,
            company_id=observation.company_id,
            domain_id=observation.domain_id,
            collector_version=observation.collector_version,
            error_category=observation.error_category,
            error_detail=observation.error_detail,
            observed_at=observation.observed_at,
            payload=observation.payload,
        )


@router.post(
    "/domains/{domain_id}/observe",
    response_model=ObservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def observe_domain(
    domain_id: UUID,
    request: ObserveRequest,
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
    dns_observer: Annotated[DnsObserverPort, Depends(dns_observer_dependency)],
    http_observer: Annotated[HttpObserverPort, Depends(http_observer_dependency)],
) -> ObservationResponse:
    idempotency_key = request.idempotency_key or uuid4().hex
    try:
        observation = run_domain_observation(
            session,
            company_id=request.company_id,
            domain_id=domain_id,
            idempotency_key=idempotency_key,
            collector_version=settings.collector_version,
            dns_observer=dns_observer,
            http_observer=http_observer,
        )
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ObservationResponse.from_model(observation)


@router.get("/domains/{domain_id}/observations", response_model=list[ObservationResponse])
def list_domain_observations(
    domain_id: UUID,
    session: Annotated[Session, Depends(session_dependency)],
) -> list[ObservationResponse]:
    observations = SqlAlchemyDomainObservationRepository(session).list_by_domain(domain_id)
    return [ObservationResponse.from_model(item) for item in observations]


@router.get("/observations/{observation_id}", response_model=ObservationResponse)
def get_observation(
    observation_id: UUID,
    session: Annotated[Session, Depends(session_dependency)],
) -> ObservationResponse:
    observation = SqlAlchemyDomainObservationRepository(session).get_by_id(observation_id)
    if observation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="observation not found")
    return ObservationResponse.from_model(observation)
