"""Pydantic contract for relationship classification output."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from domain_resolver.classification.reason_codes import ClassificationReasonCode
from domain_resolver.classification.relationship_types import (
    PartOfSubtype,
    RelationshipDirection,
    RelationshipType,
)


class ClassificationConfidenceBand(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RelationshipClassification(BaseModel):
    """Explainable, typed relationship for one canonical domain pair (a < b).

    ``primary``/``secondary`` are relationship-aware: the primary is the redirect
    target (SAME_AS), the parent (PART_OF), or the acquirer (ACQUIRED). For
    UNRELATED and REVIEW_REQUIRED there is no primary. The acquirer/acquired and
    parent/part-of views are derived from ``relationship_type`` + the primary, so
    no contradictory fields are stored.
    """

    classifier_version: str
    domain_a_id: UUID
    domain_b_id: UUID
    domain_a: str
    domain_b: str

    relationship_type: RelationshipType
    relationship_subtype: PartOfSubtype | None = None
    direction: RelationshipDirection = RelationshipDirection.UNDETERMINED

    primary_domain_id: UUID | None = None
    primary_host: str | None = None
    secondary_domain_id: UUID | None = None
    secondary_host: str | None = None

    confidence: float
    confidence_band: ClassificationConfidenceBand
    reason_codes: list[ClassificationReasonCode] = Field(default_factory=list)
    explanation: str = ""

    @property
    def acquirer_host(self) -> str | None:
        return self.primary_host if self.relationship_type is RelationshipType.ACQUIRED else None

    @property
    def acquired_host(self) -> str | None:
        return self.secondary_host if self.relationship_type is RelationshipType.ACQUIRED else None

    @property
    def parent_host(self) -> str | None:
        return self.primary_host if self.relationship_type is RelationshipType.PART_OF else None

    @property
    def part_of_host(self) -> str | None:
        return self.secondary_host if self.relationship_type is RelationshipType.PART_OF else None
