"""Phase 4 feature-extraction routes: trigger and query feature snapshots.

Exposes extraction and queries only. No matching, similarity, or decision
endpoint exists — those belong to later phases.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.dependencies import feature_extractor_dependency, session_dependency
from domain_resolver.features.errors import FeatureExtractionError
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.models.entities import ObservationFeature
from domain_resolver.repositories.sqlalchemy import SqlAlchemyObservationFeatureRepository

router = APIRouter(tags=["features"])


class FeatureResponse(BaseModel):
    id: UUID
    observation_id: UUID
    domain_id: UUID
    feature_version: str
    created_at: datetime
    features: dict[str, Any]
    warnings: list[Any] | None

    @classmethod
    def from_model(cls, feature: ObservationFeature) -> FeatureResponse:
        return cls(
            id=feature.id,
            observation_id=feature.observation_id,
            domain_id=feature.domain_id,
            feature_version=feature.feature_version,
            created_at=feature.created_at,
            features=feature.features,
            warnings=feature.warnings,
        )


@router.post(
    "/observations/{observation_id}/extract",
    response_model=FeatureResponse,
    status_code=status.HTTP_201_CREATED,
)
def extract_observation_features(
    observation_id: UUID,
    session: Annotated[Session, Depends(session_dependency)],
    extractor: Annotated[FeatureExtractor, Depends(feature_extractor_dependency)],
) -> FeatureResponse:
    try:
        snapshot = run_feature_extraction(
            session, observation_id=observation_id, extractor=extractor
        )
    except FeatureExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FeatureResponse.from_model(snapshot)


@router.get(
    "/observations/{observation_id}/features",
    response_model=list[FeatureResponse],
)
def list_observation_features(
    observation_id: UUID,
    session: Annotated[Session, Depends(session_dependency)],
) -> list[FeatureResponse]:
    snapshots = SqlAlchemyObservationFeatureRepository(session).list_by_observation(observation_id)
    return [FeatureResponse.from_model(item) for item in snapshots]


@router.get("/domains/{domain_id}/features", response_model=list[FeatureResponse])
def list_domain_features(
    domain_id: UUID,
    session: Annotated[Session, Depends(session_dependency)],
) -> list[FeatureResponse]:
    snapshots = SqlAlchemyObservationFeatureRepository(session).list_by_domain(domain_id)
    return [FeatureResponse.from_model(item) for item in snapshots]
