"""Thin SQLAlchemy implementations of DERE persistence ports."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from domain_resolver.models.entities import (
    Company,
    CrawlJob,
    Decision,
    DecisionEvidence,
    Domain,
    DomainObservation,
    DomainRelationship,
    Evidence,
    HumanReview,
    ModelVersion,
    ObservationFeature,
    RelationshipEvidence,
)


def canonical_domain_pair(domain_id_a: UUID, domain_id_b: UUID) -> tuple[UUID, UUID]:
    """Return the two domain ids in canonical (ascending) order.

    An unordered relationship pair is stored in a single deterministic direction
    so that ``(A, B)`` and ``(B, A)`` never appear as two opposite-direction
    rows. ``uuid.UUID`` compares by its 128-bit integer value, matching the total
    ordering PostgreSQL defines for the ``uuid`` type, so the same pair always
    resolves to the same direction in Python and in the database check.
    """
    if domain_id_a == domain_id_b:
        raise ValueError("a relationship requires two distinct domains")
    return (domain_id_a, domain_id_b) if domain_id_a < domain_id_b else (domain_id_b, domain_id_a)


class SqlAlchemyCompanyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, company_id: UUID) -> Company | None:
        return self._session.get(Company, company_id)

    def get_by_external_id(self, external_company_id: str) -> Company | None:
        return self._session.scalar(
            select(Company).where(Company.external_company_id == external_company_id)
        )

    def create(self, company: Company) -> Company:
        self._session.add(company)
        self._session.flush()
        return company


class SqlAlchemyDomainRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, domain_id: UUID) -> Domain | None:
        return self._session.get(Domain, domain_id)

    def get_by_hostname(self, hostname: str) -> Domain | None:
        return self._session.scalar(select(Domain).where(Domain.hostname == hostname))

    def create(self, domain: Domain) -> Domain:
        self._session.add(domain)
        self._session.flush()
        return domain


class SqlAlchemyDomainObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, observation_id: UUID) -> DomainObservation | None:
        return self._session.get(DomainObservation, observation_id)

    def create(self, observation: DomainObservation) -> DomainObservation:
        self._session.add(observation)
        self._session.flush()
        return observation

    def list_by_company(self, company_id: UUID) -> list[DomainObservation]:
        return list(
            self._session.scalars(
                select(DomainObservation)
                .where(DomainObservation.company_id == company_id)
                .order_by(DomainObservation.observed_at)
            )
        )

    def list_by_domain(self, domain_id: UUID) -> list[DomainObservation]:
        return list(
            self._session.scalars(
                select(DomainObservation)
                .where(DomainObservation.domain_id == domain_id)
                .order_by(DomainObservation.observed_at)
            )
        )


class SqlAlchemyObservationFeatureRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, feature_id: UUID) -> ObservationFeature | None:
        return self._session.get(ObservationFeature, feature_id)

    def get_by_observation_and_version(
        self, observation_id: UUID, feature_version: str
    ) -> ObservationFeature | None:
        return self._session.scalar(
            select(ObservationFeature).where(
                ObservationFeature.observation_id == observation_id,
                ObservationFeature.feature_version == feature_version,
            )
        )

    def create(self, feature: ObservationFeature) -> ObservationFeature:
        self._session.add(feature)
        self._session.flush()
        return feature

    def list_by_domain(self, domain_id: UUID) -> list[ObservationFeature]:
        return list(
            self._session.scalars(
                select(ObservationFeature)
                .where(ObservationFeature.domain_id == domain_id)
                .order_by(ObservationFeature.created_at)
            )
        )

    def list_by_observation(self, observation_id: UUID) -> list[ObservationFeature]:
        return list(
            self._session.scalars(
                select(ObservationFeature)
                .where(ObservationFeature.observation_id == observation_id)
                .order_by(ObservationFeature.created_at)
            )
        )


class SqlAlchemyDomainRelationshipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, relationship_id: UUID) -> DomainRelationship | None:
        return self._session.get(DomainRelationship, relationship_id)

    def create(self, relationship: DomainRelationship) -> DomainRelationship:
        # Canonicalize the pair direction before persisting so the database check
        # constraint (domain_a_id < domain_b_id) is always satisfied and the same
        # unordered pair is stored consistently across assessments.
        relationship.domain_a_id, relationship.domain_b_id = canonical_domain_pair(
            relationship.domain_a_id, relationship.domain_b_id
        )
        self._session.add(relationship)
        self._session.flush()
        return relationship

    def list_by_company(self, company_id: UUID) -> list[DomainRelationship]:
        return list(
            self._session.scalars(
                select(DomainRelationship)
                .where(DomainRelationship.company_id == company_id)
                .order_by(DomainRelationship.assessed_at)
            )
        )

    def list_by_domain(self, domain_id: UUID) -> list[DomainRelationship]:
        return list(
            self._session.scalars(
                select(DomainRelationship)
                .where(
                    or_(
                        DomainRelationship.domain_a_id == domain_id,
                        DomainRelationship.domain_b_id == domain_id,
                    )
                )
                .order_by(DomainRelationship.assessed_at)
            )
        )


class SqlAlchemyEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, evidence_id: UUID) -> Evidence | None:
        return self._session.get(Evidence, evidence_id)

    def create(self, evidence: Evidence) -> Evidence:
        self._session.add(evidence)
        self._session.flush()
        return evidence

    def list_by_domain(self, domain_id: UUID) -> list[Evidence]:
        return list(
            self._session.scalars(
                select(Evidence)
                .where(or_(Evidence.domain_a_id == domain_id, Evidence.domain_b_id == domain_id))
                .order_by(Evidence.observed_at)
            )
        )


class SqlAlchemyDecisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, decision_id: UUID) -> Decision | None:
        return self._session.get(Decision, decision_id)

    def create(self, decision: Decision) -> Decision:
        self._session.add(decision)
        self._session.flush()
        return decision

    def list_by_company(self, company_id: UUID) -> list[Decision]:
        return list(
            self._session.scalars(
                select(Decision)
                .where(Decision.company_id == company_id)
                .order_by(Decision.decided_at)
            )
        )


class SqlAlchemyHumanReviewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, review_id: UUID) -> HumanReview | None:
        return self._session.get(HumanReview, review_id)

    def create(self, review: HumanReview) -> HumanReview:
        self._session.add(review)
        self._session.flush()
        return review

    def list_by_decision(self, decision_id: UUID) -> list[HumanReview]:
        return list(
            self._session.scalars(
                select(HumanReview)
                .where(HumanReview.decision_id == decision_id)
                .order_by(HumanReview.reviewed_at)
            )
        )


class SqlAlchemyModelVersionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, model_version_id: UUID) -> ModelVersion | None:
        return self._session.get(ModelVersion, model_version_id)

    def get_by_version(self, version: str) -> ModelVersion | None:
        return self._session.scalar(select(ModelVersion).where(ModelVersion.version == version))

    def create(self, model_version: ModelVersion) -> ModelVersion:
        self._session.add(model_version)
        self._session.flush()
        return model_version


class SqlAlchemyCrawlJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, crawl_job_id: UUID) -> CrawlJob | None:
        return self._session.get(CrawlJob, crawl_job_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> CrawlJob | None:
        return self._session.scalar(
            select(CrawlJob).where(CrawlJob.idempotency_key == idempotency_key)
        )

    def create(self, crawl_job: CrawlJob) -> CrawlJob:
        self._session.add(crawl_job)
        self._session.flush()
        return crawl_job

    def save(self, crawl_job: CrawlJob) -> CrawlJob:
        self._session.add(crawl_job)
        self._session.flush()
        return crawl_job


class SqlAlchemyDecisionEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def link(self, decision_id: UUID, evidence_id: UUID) -> DecisionEvidence:
        link = DecisionEvidence(decision_id=decision_id, evidence_id=evidence_id)
        self._session.add(link)
        self._session.flush()
        return link

    def list_evidence_for_decision(self, decision_id: UUID) -> list[Evidence]:
        return list(
            self._session.scalars(
                select(Evidence)
                .join(DecisionEvidence, DecisionEvidence.evidence_id == Evidence.id)
                .where(DecisionEvidence.decision_id == decision_id)
                .order_by(Evidence.observed_at)
            )
        )


class SqlAlchemyRelationshipEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def link(self, relationship_id: UUID, evidence_id: UUID) -> RelationshipEvidence:
        link = RelationshipEvidence(relationship_id=relationship_id, evidence_id=evidence_id)
        self._session.add(link)
        self._session.flush()
        return link

    def list_evidence_for_relationship(self, relationship_id: UUID) -> list[Evidence]:
        return list(
            self._session.scalars(
                select(Evidence)
                .join(RelationshipEvidence, RelationshipEvidence.evidence_id == Evidence.id)
                .where(RelationshipEvidence.relationship_id == relationship_id)
                .order_by(Evidence.observed_at)
            )
        )
