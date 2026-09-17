"""Integration tests that require a real PostgreSQL database."""

import csv
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError

from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.models.entities import (
    Company,
    Decision,
    DecisionStatus,
    Domain,
    DomainObservation,
    ModelVersion,
    ModelVersionKind,
)
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyCompanyRepository,
    SqlAlchemyDomainObservationRepository,
    SqlAlchemyDomainRepository,
)

pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "same_as_examples.csv"
EXPECTED_TABLES = {
    "alembic_version",
    "companies",
    "crawl_jobs",
    "decision_evidence",
    "decisions",
    "domain_observations",
    "domain_relationships",
    "domains",
    "evidence",
    "human_review_secondary_domains",
    "human_reviews",
    "model_versions",
    "observation_features",
    "relationship_evidence",
}


def test_database_connection_works(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        assert connection.execute(select(1)).scalar_one() == 1


def test_migration_upgrade_downgrade_and_schema(
    alembic_config: Config, migrated_engine: Engine
) -> None:
    assert EXPECTED_TABLES.issubset(set(inspect(migrated_engine).get_table_names()))

    command.downgrade(alembic_config, "base")
    assert not (EXPECTED_TABLES - {"alembic_version"}).intersection(
        inspect(migrated_engine).get_table_names()
    )

    command.upgrade(alembic_config, "head")
    assert EXPECTED_TABLES.issubset(set(inspect(migrated_engine).get_table_names()))


def test_foreign_keys_and_unique_constraints(migrated_engine: Engine) -> None:
    session_factory = create_session_factory(migrated_engine)
    with pytest.raises(IntegrityError):
        with session_scope(session_factory) as session:
            session.add(Domain(hostname="duplicate.example"))
            session.flush()
            session.add(Domain(hostname="duplicate.example"))

    with pytest.raises(IntegrityError):
        with session_scope(session_factory) as session:
            session.add(
                DomainObservation(
                    company_id=UUID("00000000-0000-0000-0000-000000000001"),
                    domain_id=UUID("00000000-0000-0000-0000-000000000001"),
                    raw_domain="missing.example",
                )
            )


def test_repositories_and_historical_observations(migrated_engine: Engine) -> None:
    session_factory = create_session_factory(migrated_engine)
    with session_scope(session_factory) as session:
        companies = SqlAlchemyCompanyRepository(session)
        domains = SqlAlchemyDomainRepository(session)
        observations = SqlAlchemyDomainObservationRepository(session)
        company = companies.create(
            Company(
                external_company_id="fixture-company",
                name_raw="Fixture Co",
                name_normalized="fixture co",
            )
        )
        domain = domains.create(Domain(hostname="fixture.example"))
        observations.create(
            DomainObservation(
                company_id=company.id,
                domain_id=domain.id,
                raw_domain="fixture.example",
                source="fixture-a",
            )
        )
        observations.create(
            DomainObservation(
                company_id=company.id,
                domain_id=domain.id,
                raw_domain="fixture.example",
                source="fixture-b",
            )
        )
        assert companies.get_by_external_id("fixture-company") == company
        assert domains.get_by_hostname("fixture.example") == domain
        assert [item.source for item in observations.list_by_domain(domain.id)] == [
            "fixture-a",
            "fixture-b",
        ]


def test_transaction_rolls_back_on_failure(migrated_engine: Engine) -> None:
    session_factory = create_session_factory(migrated_engine)
    with pytest.raises(RuntimeError):
        with session_scope(session_factory) as session:
            session.add(Domain(hostname="rolled-back.example"))
            raise RuntimeError("intentional rollback")

    with session_scope(session_factory) as session:
        assert (
            session.scalar(select(Domain).where(Domain.hostname == "rolled-back.example")) is None
        )


def test_same_as_gold_fixture_is_representable_without_matching_logic(
    migrated_engine: Engine,
) -> None:
    session_factory = create_session_factory(migrated_engine)
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as fixture_file:
        rows = list(csv.DictReader(fixture_file))

    with session_scope(session_factory) as session:
        model_version = ModelVersion(
            version="fixture-label-import-v1",
            kind=ModelVersionKind.FEATURE_CONFIGURATION,
            configuration={"purpose": "test-fixture-only"},
        )
        session.add(model_version)
        for index, row in enumerate(rows, start=1):
            company = Company(
                external_company_id=f"fixture-same-as-{index}",
                name_raw=f"Fixture Company {index}",
                name_normalized=f"fixture company {index}",
            )
            secondary = Domain(hostname=row["secondary_domain"])
            primary = Domain(hostname=row["primary_domain"])
            session.add_all([company, secondary, primary])
            session.flush()
            session.add_all(
                [
                    DomainObservation(
                        company_id=company.id,
                        domain_id=secondary.id,
                        raw_domain=secondary.hostname,
                        source="CPT_GOLD_FIXTURE",
                    ),
                    DomainObservation(
                        company_id=company.id,
                        domain_id=primary.id,
                        raw_domain=primary.hostname,
                        source="CPT_GOLD_FIXTURE",
                    ),
                    Decision(
                        company_id=company.id,
                        primary_domain_id=primary.id,
                        status=DecisionStatus.AUTO_ACCEPT,
                        model_version_id=model_version.id,
                        outcome_payload={
                            "fixture_label": "CPT_GOLD",
                            "secondary_domains": [secondary.hostname],
                        },
                    ),
                ]
            )

    with session_scope(session_factory) as session:
        assert session.scalar(select(func.count()).select_from(Decision)) == 14
