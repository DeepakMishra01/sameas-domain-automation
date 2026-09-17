"""PostgreSQL integration tests for the Phase 2 remediation guarantees.

These require a real database (``DERE_TEST_DATABASE_URL``) because they assert
runtime behaviour: append-safe reason codes, relational evidence traceability,
foreign-key protection, ``updated_at`` refresh, and canonical relationship pairs.
They are skipped — never substituted with SQLite — when no database is set.
"""

from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError

from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.models.entities import (
    Company,
    CrawlJob,
    CrawlJobStatus,
    Decision,
    DecisionEvidence,
    DecisionStatus,
    Domain,
    DomainRelationship,
    Evidence,
    EvidenceStrength,
    ModelVersion,
    ModelVersionKind,
    RelationshipState,
)
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyDecisionEvidenceRepository,
    SqlAlchemyDomainRelationshipRepository,
    SqlAlchemyRelationshipEvidenceRepository,
)

pytestmark = pytest.mark.integration


def _make_evidence(reason_code: str, source: str) -> Evidence:
    return Evidence(
        reason_code=reason_code,
        evidence_type="ORGANIZATION_SIGNAL",
        source=source,
        strength=EvidenceStrength.SUPPORTING,
    )


def test_reason_code_is_reusable_across_evidence_rows(migrated_engine: Engine) -> None:
    """H2: the same reason code must be appendable many times."""
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        session.add(_make_evidence("SAME_PHONE", "crawl-1"))
        session.add(_make_evidence("SAME_PHONE", "crawl-2"))
        session.add(_make_evidence("SAME_PHONE", "crawl-3"))

    with session_scope(session_factory) as session:
        count = session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.reason_code == "SAME_PHONE")
        )
        assert count == 3


def test_decision_evidence_link_is_relational_and_retrievable(migrated_engine: Engine) -> None:
    """H3: a decision is traceable to evidence through a relational link."""
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        company = Company(
            external_company_id="link-co",
            name_raw="Link Co",
            name_normalized="link co",
        )
        model_version = ModelVersion(
            version="link-v1",
            kind=ModelVersionKind.RULES,
            configuration={},
        )
        session.add_all([company, model_version])
        session.flush()
        decision = Decision(
            company_id=company.id,
            status=DecisionStatus.REVIEW_REQUIRED,
            model_version_id=model_version.id,
            outcome_payload={},
        )
        evidence = _make_evidence("OFFICIAL_WEBSITE_REFERENCE", "crawl-1")
        session.add_all([decision, evidence])
        session.flush()

        links = SqlAlchemyDecisionEvidenceRepository(session)
        links.link(decision.id, evidence.id)

        retrieved = links.list_evidence_for_decision(decision.id)
        assert [item.id for item in retrieved] == [evidence.id]


def test_decision_evidence_rejects_nonexistent_evidence(migrated_engine: Engine) -> None:
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        company = Company(external_company_id="fk-co", name_raw="FK Co", name_normalized="fk co")
        model_version = ModelVersion(version="fk-v1", kind=ModelVersionKind.RULES, configuration={})
        session.add_all([company, model_version])
        session.flush()
        decision = Decision(
            company_id=company.id,
            status=DecisionStatus.REVIEW_REQUIRED,
            model_version_id=model_version.id,
            outcome_payload={},
        )
        session.add(decision)
        session.flush()
        decision_id = decision.id

    with pytest.raises(IntegrityError):
        with session_scope(session_factory) as session:
            session.add(DecisionEvidence(decision_id=decision_id, evidence_id=uuid4()))


def test_decision_evidence_pair_is_unique(migrated_engine: Engine) -> None:
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        company = Company(external_company_id="uq-co", name_raw="UQ Co", name_normalized="uq co")
        model_version = ModelVersion(version="uq-v1", kind=ModelVersionKind.RULES, configuration={})
        session.add_all([company, model_version])
        session.flush()
        decision = Decision(
            company_id=company.id,
            status=DecisionStatus.REVIEW_REQUIRED,
            model_version_id=model_version.id,
            outcome_payload={},
        )
        evidence = _make_evidence("REDIRECT", "crawl-1")
        session.add_all([decision, evidence])
        session.flush()
        decision_id, evidence_id = decision.id, evidence.id

    with pytest.raises(IntegrityError):
        with session_scope(session_factory) as session:
            session.add(DecisionEvidence(decision_id=decision_id, evidence_id=evidence_id))
            session.flush()
            session.add(DecisionEvidence(decision_id=decision_id, evidence_id=evidence_id))


def test_relationship_evidence_link_is_relational(migrated_engine: Engine) -> None:
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        company = Company(external_company_id="rel-co", name_raw="Rel Co", name_normalized="rel co")
        model_version = ModelVersion(
            version="rel-v1", kind=ModelVersionKind.RULES, configuration={}
        )
        domain_a = Domain(hostname="rel-a.example")
        domain_b = Domain(hostname="rel-b.example")
        session.add_all([company, model_version, domain_a, domain_b])
        session.flush()
        relationships = SqlAlchemyDomainRelationshipRepository(session)
        relationship = relationships.create(
            DomainRelationship(
                company_id=company.id,
                domain_a_id=domain_a.id,
                domain_b_id=domain_b.id,
                state=RelationshipState.SAME_ORGANIZATION,
                model_version_id=model_version.id,
            )
        )
        evidence = _make_evidence("SAME_COMPANY_NAME", "crawl-1")
        session.add(evidence)
        session.flush()

        links = SqlAlchemyRelationshipEvidenceRepository(session)
        links.link(relationship.id, evidence.id)
        assert [item.id for item in links.list_evidence_for_relationship(relationship.id)] == [
            evidence.id
        ]


def test_crawl_job_updated_at_changes_on_update(migrated_engine: Engine) -> None:
    """M2: a mutable crawl job records when its state last changed."""
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        domain = Domain(hostname="crawl.example")
        session.add(domain)
        session.flush()
        job = CrawlJob(
            domain_id=domain.id,
            correlation_id="corr-1",
            idempotency_key="idem-1",
        )
        session.add(job)
        session.flush()
        job_id = job.id
        original_updated_at = job.updated_at

    with session_scope(session_factory) as session:
        job = session.get(CrawlJob, job_id)
        assert job is not None
        job.status = CrawlJobStatus.RUNNING

    with session_scope(session_factory) as session:
        job = session.get(CrawlJob, job_id)
        assert job is not None
        assert job.status is CrawlJobStatus.RUNNING
        assert job.updated_at != original_updated_at


def test_relationship_pair_is_stored_canonically(migrated_engine: Engine) -> None:
    """M3: (A, B) and (B, A) resolve to the same canonical direction, and
    multiple historical model versions of that pair are allowed."""
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        company = Company(
            external_company_id="pair-co", name_raw="Pair Co", name_normalized="pair co"
        )
        version_one = ModelVersion(version="pair-v1", kind=ModelVersionKind.RULES, configuration={})
        version_two = ModelVersion(version="pair-v2", kind=ModelVersionKind.RULES, configuration={})
        domain_a = Domain(hostname="pair-a.example")
        domain_b = Domain(hostname="pair-b.example")
        session.add_all([company, version_one, version_two, domain_a, domain_b])
        session.flush()
        canonical_low = min(domain_a.id, domain_b.id)
        relationships = SqlAlchemyDomainRelationshipRepository(session)

        forward = relationships.create(
            DomainRelationship(
                company_id=company.id,
                domain_a_id=domain_a.id,
                domain_b_id=domain_b.id,
                state=RelationshipState.SAME_ORGANIZATION,
                model_version_id=version_one.id,
            )
        )
        reverse = relationships.create(
            DomainRelationship(
                company_id=company.id,
                domain_a_id=domain_b.id,
                domain_b_id=domain_a.id,
                state=RelationshipState.SAME_ORGANIZATION,
                model_version_id=version_two.id,
            )
        )

        assert forward.domain_a_id == reverse.domain_a_id == canonical_low
        assert forward.domain_b_id == reverse.domain_b_id
        # Both historical assessments are retained (append, not overwrite).
        assert (
            session.scalar(
                select(func.count())
                .select_from(DomainRelationship)
                .where(DomainRelationship.company_id == company.id)
            )
            == 2
        )


def test_noncanonical_relationship_is_rejected_by_the_database(migrated_engine: Engine) -> None:
    """The check constraint guards against direct, non-canonical inserts."""
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        company = Company(external_company_id="raw-co", name_raw="Raw Co", name_normalized="raw co")
        model_version = ModelVersion(
            version="raw-v1", kind=ModelVersionKind.RULES, configuration={}
        )
        domain_a = Domain(hostname="raw-a.example")
        domain_b = Domain(hostname="raw-b.example")
        session.add_all([company, model_version, domain_a, domain_b])
        session.flush()
        high = max(domain_a.id, domain_b.id)
        low = min(domain_a.id, domain_b.id)
        company_id, version_id = company.id, model_version.id

    with pytest.raises(IntegrityError):
        with session_scope(session_factory) as session:
            # Bypass the canonicalizing repository to hit the raw check constraint.
            session.add(
                DomainRelationship(
                    company_id=company_id,
                    domain_a_id=high,
                    domain_b_id=low,
                    state=RelationshipState.SAME_ORGANIZATION,
                    model_version_id=version_id,
                )
            )
