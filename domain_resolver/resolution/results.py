"""Pydantic contracts for primary-domain resolution output."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from domain_resolver.resolution.reason_codes import PrimaryReasonCode


class PrimaryDesignation(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    UNRESOLVED = "UNRESOLVED"


class ResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class PrimaryConfidenceBand(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DomainScore(BaseModel):
    domain_id: UUID
    host: str
    primary_score: float
    designation: PrimaryDesignation
    reason_codes: list[PrimaryReasonCode] = Field(default_factory=list)
    negative_reason_codes: list[PrimaryReasonCode] = Field(default_factory=list)


class PrimaryResolution(BaseModel):
    """Explainable primary/secondary resolution for one same-org group."""

    resolver_version: str
    status: ResolutionStatus
    primary_domain_id: UUID | None = None
    primary_host: str | None = None
    confidence: float
    confidence_band: PrimaryConfidenceBand
    margin: float
    scores: list[DomainScore] = Field(default_factory=list)
    conflicts: list[dict[str, object]] = Field(default_factory=list)
