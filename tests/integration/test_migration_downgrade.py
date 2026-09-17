"""Regression tests for safe Phase 3 -> Phase 2 migration downgrade.

Phase 3 makes ``evidence.strength`` nullable and stores factual evidence with
``strength IS NULL``. Downgrading to Phase 2 (which requires ``strength NOT
NULL``) must not fail on, or discard, those rows. Requires PostgreSQL.
"""

import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from domain_resolver.infrastructure.database import create_engine_from_url

pytestmark = pytest.mark.integration

PHASE2_REVISION = "20260917_0001"

_INSERT_EVIDENCE = text(
    "INSERT INTO evidence "
    "(id, reason_code, evidence_type, source, strength, created_at, observed_at) "
    "VALUES (:id, 'REDIRECT', 'HTTP_REDIRECT', 'domain-observer-test', :strength, now(), now())"
)


def test_downgrade_is_safe_with_null_strength_evidence(
    alembic_config: Config, test_database_url: str
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    engine = create_engine_from_url(test_database_url)
    evidence_id = uuid.uuid4()
    try:
        # A factual Phase 3 evidence row carries no asserted weight.
        with engine.begin() as conn:
            conn.execute(_INSERT_EVIDENCE, {"id": evidence_id, "strength": None})
            assert (
                conn.execute(
                    text("SELECT strength FROM evidence WHERE id = :id"), {"id": evidence_id}
                ).scalar_one()
                is None
            )

        # The downgrade must succeed despite the null-strength row.
        command.downgrade(alembic_config, PHASE2_REVISION)

        columns = {c["name"]: c for c in inspect(engine).get_columns("evidence")}
        # Phase 2 schema restored exactly: strength NOT NULL, no observation_id.
        assert columns["strength"]["nullable"] is False
        assert "observation_id" not in columns

        with engine.connect() as conn:
            # The row is preserved (not deleted) and backfilled to a valid value.
            assert (
                conn.execute(
                    text("SELECT strength FROM evidence WHERE id = :id"), {"id": evidence_id}
                ).scalar_one()
                == "WEAK"
            )

        # The restored NOT NULL constraint genuinely rejects a null strength.
        with pytest.raises(Exception):  # noqa: B017 - driver-specific IntegrityError
            with engine.begin() as conn:
                conn.execute(_INSERT_EVIDENCE, {"id": uuid.uuid4(), "strength": None})

    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_roundtrip(
    alembic_config: Config, test_database_url: str
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    engine = create_engine_from_url(test_database_url)
    evidence_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            conn.execute(_INSERT_EVIDENCE, {"id": evidence_id, "strength": None})

        command.downgrade(alembic_config, PHASE2_REVISION)
        command.upgrade(alembic_config, "head")

        columns = {c["name"]: c for c in inspect(engine).get_columns("evidence")}
        # Back at Phase 3: strength nullable again and observation_id present.
        assert columns["strength"]["nullable"] is True
        assert "observation_id" in columns

        with engine.connect() as conn:
            # Data survives the round trip, holding the backfilled value.
            assert (
                conn.execute(
                    text("SELECT strength FROM evidence WHERE id = :id"), {"id": evidence_id}
                ).scalar_one()
                == "WEAK"
            )
    finally:
        engine.dispose()
