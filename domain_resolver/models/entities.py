"""Historical PostgreSQL persistence models for DERE."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from domain_resolver.models.base import (
    Base,
    MutableTimestampMixin,
    UUIDTimestampMixin,
    utc_now,
)


class DomainState(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    UNRELATED = "UNRELATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN"
    DEAD = "DEAD"
    PARKED = "PARKED"
    REDIRECT = "REDIRECT"


class RelationshipState(StrEnum):
    SAME_ORGANIZATION = "SAME_ORGANIZATION"
    UNRELATED = "UNRELATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN"


class DecisionStatus(StrEnum):
    AUTO_ACCEPT = "AUTO_ACCEPT"
    AUTO_REJECT = "AUTO_REJECT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EvidenceStrength(StrEnum):
    VERY_STRONG = "VERY_STRONG"
    STRONG = "STRONG"
    SUPPORTING = "SUPPORTING"
    WEAK = "WEAK"


class CrawlJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class CrawlErrorCategory(StrEnum):
    DNS_ERROR = "DNS_ERROR"
    TIMEOUT = "TIMEOUT"
    ROBOTS_BLOCKED = "ROBOTS_BLOCKED"
    HTTP_403 = "HTTP_403"
    HTTP_429 = "HTTP_429"
    HTTP_5XX = "HTTP_5XX"
    SSL_ERROR = "SSL_ERROR"
    PARSER_ERROR = "PARSER_ERROR"
    JS_RENDER_ERROR = "JS_RENDER_ERROR"


class ModelVersionKind(StrEnum):
    RULES = "RULES"
    MODEL = "MODEL"
    FEATURE_CONFIGURATION = "FEATURE_CONFIGURATION"


class ObservationErrorCategory(StrEnum):
    """Factual, reliably-classifiable failure categories for domain observation.

    These describe *what failed while observing*, never a relationship judgement.
    A value is recorded only when the underlying failure can be classified with
    confidence; ambiguous failures are left uncategorised with detail preserved.
    """

    DNS_ERROR = "DNS_ERROR"
    TIMEOUT = "TIMEOUT"
    ROBOTS_BLOCKED = "ROBOTS_BLOCKED"
    HTTP_403 = "HTTP_403"
    HTTP_429 = "HTTP_429"
    HTTP_4XX = "HTTP_4XX"
    HTTP_5XX = "HTTP_5XX"
    SSL_ERROR = "SSL_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    PARSER_ERROR = "PARSER_ERROR"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    REDIRECT_LIMIT = "REDIRECT_LIMIT"
    SSRF_BLOCKED = "SSRF_BLOCKED"


class Company(UUIDTimestampMixin, MutableTimestampMixin, Base):
    __tablename__ = "companies"

    external_company_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name_raw: Mapped[str] = mapped_column(String(512))
    name_normalized: Mapped[str] = mapped_column(String(512), index=True)

    observations: Mapped[list["DomainObservation"]] = relationship()
    relationships: Mapped[list["DomainRelationship"]] = relationship()
    decisions: Mapped[list["Decision"]] = relationship()


class Domain(UUIDTimestampMixin, Base):
    __tablename__ = "domains"

    hostname: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    observations: Mapped[list["DomainObservation"]] = relationship()
    crawl_jobs: Mapped[list["CrawlJob"]] = relationship()
    evidence_as_a: Mapped[list["Evidence"]] = relationship(foreign_keys="Evidence.domain_a_id")
    evidence_as_b: Mapped[list["Evidence"]] = relationship(foreign_keys="Evidence.domain_b_id")
    relationships_as_a: Mapped[list["DomainRelationship"]] = relationship(
        foreign_keys="DomainRelationship.domain_a_id"
    )
    relationships_as_b: Mapped[list["DomainRelationship"]] = relationship(
        foreign_keys="DomainRelationship.domain_b_id"
    )
    primary_decisions: Mapped[list["Decision"]] = relationship()
    corrected_primary_reviews: Mapped[list["HumanReview"]] = relationship()
    secondary_review_links: Mapped[list["HumanReviewSecondaryDomain"]] = relationship()


class DomainObservation(UUIDTimestampMixin, Base):
    __tablename__ = "domain_observations"

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    domain_id: Mapped[UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str | None] = mapped_column(String(128))
    raw_domain: Mapped[str] = mapped_column(String(2048))
    state: Mapped[DomainState] = mapped_column(
        Enum(DomainState, name="domain_state", native_enum=False, create_constraint=True),
        default=DomainState.UNKNOWN,
        server_default=DomainState.UNKNOWN.value,
    )
    # Identifies the collector that produced this observation, so historical rows
    # remain attributable across collector versions. Nullable for rows created by
    # non-observer paths; the observer always sets it.
    collector_version: Mapped[str | None] = mapped_column(String(64), index=True)
    error_category: Mapped[ObservationErrorCategory | None] = mapped_column(
        Enum(
            ObservationErrorCategory,
            name="observation_error_category",
            native_enum=False,
            create_constraint=True,
        )
    )
    error_detail: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), index=True
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    company: Mapped[Company] = relationship(back_populates="observations")
    domain: Mapped[Domain] = relationship(back_populates="observations")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="observation")
    features: Mapped[list["ObservationFeature"]] = relationship(back_populates="observation")


class CrawlJob(UUIDTimestampMixin, MutableTimestampMixin, Base):
    __tablename__ = "crawl_jobs"

    domain_id: Mapped[UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[CrawlJobStatus] = mapped_column(
        Enum(CrawlJobStatus, name="crawl_job_status", native_enum=False, create_constraint=True),
        default=CrawlJobStatus.PENDING,
        server_default=CrawlJobStatus.PENDING.value,
    )
    error_category: Mapped[CrawlErrorCategory | None] = mapped_column(
        Enum(
            CrawlErrorCategory,
            name="crawl_error_category",
            native_enum=False,
            create_constraint=True,
        )
    )
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    domain: Mapped[Domain] = relationship(back_populates="crawl_jobs")


class Evidence(UUIDTimestampMixin, Base):
    __tablename__ = "evidence"

    # ``reason_code`` is a reusable taxonomy value (for example ``SAME_PHONE`` or
    # ``REDIRECT``), never a globally unique row identifier. The append-only
    # evidence model requires the same code to recur across companies, domains,
    # observations, and crawl times, so it is indexed but intentionally not unique.
    reason_code: Mapped[str] = mapped_column(String(64), index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(128))
    domain_a_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    domain_b_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    value: Mapped[bool | None] = mapped_column(Boolean)
    # Strength is an interpretive weight and is intentionally optional: factual
    # observation evidence (Phase 3) asserts no validated weight and leaves it null.
    strength: Mapped[EvidenceStrength | None] = mapped_column(
        Enum(EvidenceStrength, name="evidence_strength", native_enum=False, create_constraint=True)
    )
    # Traceability to the observation that produced this factual evidence.
    observation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("domain_observations.id", ondelete="RESTRICT"), index=True
    )
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), index=True
    )

    domain_a: Mapped[Domain | None] = relationship(
        back_populates="evidence_as_a", foreign_keys=[domain_a_id]
    )
    domain_b: Mapped[Domain | None] = relationship(
        back_populates="evidence_as_b", foreign_keys=[domain_b_id]
    )
    observation: Mapped["DomainObservation | None"] = relationship(back_populates="evidence")
    decision_links: Mapped[list["DecisionEvidence"]] = relationship(back_populates="evidence")
    relationship_links: Mapped[list["RelationshipEvidence"]] = relationship(
        back_populates="evidence"
    )


class ModelVersion(UUIDTimestampMixin, Base):
    __tablename__ = "model_versions"

    version: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[ModelVersionKind] = mapped_column(
        Enum(
            ModelVersionKind,
            name="model_version_kind",
            native_enum=False,
            create_constraint=True,
        )
    )
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON)

    relationships: Mapped[list["DomainRelationship"]] = relationship()
    decisions: Mapped[list["Decision"]] = relationship()


class DomainRelationship(UUIDTimestampMixin, Base):
    __tablename__ = "domain_relationships"
    __table_args__ = (
        # Store every pair in a single canonical direction (smaller domain id
        # first). This makes an unordered pair deterministic and forbids the same
        # logical pair being stored as two opposite-direction rows, while still
        # allowing multiple historical assessments (different model versions or
        # re-assessments) of that canonical pair. ``<`` also implies inequality,
        # replacing the previous ``different_domains`` check. PostgreSQL defines a
        # total btree ordering for the ``uuid`` type, so this comparison is safe.
        CheckConstraint("domain_a_id < domain_b_id", name="canonical_domain_order"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    domain_a_id: Mapped[UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    domain_b_id: Mapped[UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    same_organization: Mapped[bool | None] = mapped_column(Boolean)
    state: Mapped[RelationshipState] = mapped_column(
        Enum(
            RelationshipState,
            name="relationship_state",
            native_enum=False,
            create_constraint=True,
        ),
        default=RelationshipState.UNKNOWN,
        server_default=RelationshipState.UNKNOWN.value,
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    model_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), index=True
    )
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), index=True
    )

    company: Mapped[Company] = relationship(back_populates="relationships")
    domain_a: Mapped[Domain] = relationship(
        back_populates="relationships_as_a", foreign_keys=[domain_a_id]
    )
    domain_b: Mapped[Domain] = relationship(
        back_populates="relationships_as_b", foreign_keys=[domain_b_id]
    )
    model_version: Mapped[ModelVersion] = relationship(back_populates="relationships")
    evidence_links: Mapped[list["RelationshipEvidence"]] = relationship(
        back_populates="domain_relationship"
    )


class Decision(UUIDTimestampMixin, Base):
    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    primary_domain_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT")
    )
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, name="decision_status", native_enum=False, create_constraint=True),
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    model_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), index=True
    )
    outcome_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), index=True
    )

    company: Mapped[Company] = relationship(back_populates="decisions")
    primary_domain: Mapped[Domain | None] = relationship(back_populates="primary_decisions")
    model_version: Mapped[ModelVersion] = relationship(back_populates="decisions")
    reviews: Mapped[list["HumanReview"]] = relationship()
    evidence_links: Mapped[list["DecisionEvidence"]] = relationship(back_populates="decision")


class HumanReview(UUIDTimestampMixin, Base):
    __tablename__ = "human_reviews"

    decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="RESTRICT"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(256))
    decision: Mapped[DecisionStatus] = mapped_column(
        Enum(
            DecisionStatus,
            name="review_decision_status",
            native_enum=False,
            create_constraint=True,
        )
    )
    corrected_primary_domain_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    source_decision: Mapped[Decision] = relationship(back_populates="reviews")
    corrected_primary_domain: Mapped[Domain | None] = relationship(
        back_populates="corrected_primary_reviews"
    )
    secondary_domains: Mapped[list["HumanReviewSecondaryDomain"]] = relationship()


class HumanReviewSecondaryDomain(UUIDTimestampMixin, Base):
    __tablename__ = "human_review_secondary_domains"
    __table_args__ = (UniqueConstraint("human_review_id", "domain_id"),)

    human_review_id: Mapped[UUID] = mapped_column(
        ForeignKey("human_reviews.id", ondelete="RESTRICT"), index=True
    )
    domain_id: Mapped[UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )

    human_review: Mapped[HumanReview] = relationship(back_populates="secondary_domains")
    domain: Mapped[Domain] = relationship(back_populates="secondary_review_links")


class DecisionEvidence(UUIDTimestampMixin, Base):
    """Relational link making a decision traceable to the evidence it rests on.

    Structured payloads may still live in ``Evidence.raw_payload`` and
    ``Decision.outcome_payload``, but evidence attribution itself is relational
    and foreign-key protected rather than expressed only through opaque JSON.
    """

    __tablename__ = "decision_evidence"
    __table_args__ = (UniqueConstraint("decision_id", "evidence_id"),)

    decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="RESTRICT"), index=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"), index=True
    )

    decision: Mapped[Decision] = relationship(back_populates="evidence_links")
    evidence: Mapped[Evidence] = relationship(back_populates="decision_links")


class RelationshipEvidence(UUIDTimestampMixin, Base):
    """Relational link making a same-organization assessment traceable to evidence."""

    __tablename__ = "relationship_evidence"
    __table_args__ = (UniqueConstraint("relationship_id", "evidence_id"),)

    relationship_id: Mapped[UUID] = mapped_column(
        ForeignKey("domain_relationships.id", ondelete="RESTRICT"), index=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"), index=True
    )

    domain_relationship: Mapped[DomainRelationship] = relationship(back_populates="evidence_links")
    evidence: Mapped[Evidence] = relationship(back_populates="relationship_links")


class ObservationFeature(UUIDTimestampMixin, Base):
    """Append-only, versioned normalized feature snapshot for one observation.

    A snapshot is unique per (observation, feature_version): re-running the same
    extractor version is idempotent, while a new extractor version produces a new
    snapshot that coexists with older versions (history is never overwritten).
    """

    __tablename__ = "observation_features"
    __table_args__ = (UniqueConstraint("observation_id", "feature_version"),)

    observation_id: Mapped[UUID] = mapped_column(
        ForeignKey("domain_observations.id", ondelete="RESTRICT"), index=True
    )
    domain_id: Mapped[UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    feature_version: Mapped[str] = mapped_column(String(64), index=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSON)
    warnings: Mapped[list[Any] | None] = mapped_column(JSON)

    observation: Mapped[DomainObservation] = relationship(back_populates="features")
    domain: Mapped[Domain] = relationship()
