"""Operational health endpoint."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.dependencies import settings_dependency
from domain_resolver.config.settings import Settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Minimal, non-sensitive service health response."""

    status: Literal["ok"]
    service: Literal["dere"]
    environment: str
    model_version: str


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> HealthResponse:
    """Report process availability without probing external dependencies."""
    return HealthResponse(
        status="ok",
        service="dere",
        environment=settings.environment,
        model_version=settings.model_version,
    )
