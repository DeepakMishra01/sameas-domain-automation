"""Static, database-free contract tests for the remediated schema.

These assert structural guarantees directly on the SQLAlchemy metadata so they
run without PostgreSQL. Behavioural guarantees that require a live database
(actual insertions, constraint enforcement, ``updated_at`` refresh) live in the
PostgreSQL integration suite and are skipped when no database is configured.
"""

import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from domain_resolver.models import Base
from domain_resolver.repositories.sqlalchemy import canonical_domain_pair

# The check-constraint names the ORM must emit. These are identical to the names
# produced by the Alembic migration (M1: ORM/migration naming consistency).
EXPECTED_CHECK_NAMES = {
    "ck_crawl_jobs_crawl_error_category",
    "ck_crawl_jobs_crawl_job_status",
    "ck_decisions_confidence_range",
    "ck_decisions_decision_status",
    "ck_domain_observations_domain_state",
    "ck_domain_observations_observation_error_category",
    "ck_domain_relationships_canonical_domain_order",
    "ck_domain_relationships_confidence_range",
    "ck_domain_relationships_relationship_state",
    "ck_evidence_evidence_strength",
    "ck_human_reviews_review_decision_status",
    "ck_model_versions_model_version_kind",
}


def _orm_check_names() -> set[str]:
    dialect = postgresql.dialect()
    names: set[str] = set()
    for table in Base.metadata.tables.values():
        ddl = str(CreateTable(table).compile(dialect=dialect))
        names.update(re.findall(r"CONSTRAINT (ck_\w+) CHECK", ddl))
    return names


def test_enum_check_constraint_names_are_consistent() -> None:
    assert _orm_check_names() == EXPECTED_CHECK_NAMES


def test_evidence_reason_code_is_not_globally_unique() -> None:
    evidence = Base.metadata.tables["evidence"]
    assert "reason_code" in evidence.c
    assert "evidence_code" not in evidence.c
    assert not evidence.c.reason_code.unique
    unique_constraints = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in evidence.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("reason_code",) not in unique_constraints
    # reason_code remains indexed for lookup even though it is not unique.
    assert any("reason_code" in {c.name for c in index.columns} for index in evidence.indexes)


def test_evidence_link_tables_have_unique_pairs_and_restrict_fks() -> None:
    for table_name, columns in (
        ("decision_evidence", ("decision_id", "evidence_id")),
        ("relationship_evidence", ("relationship_id", "evidence_id")),
    ):
        table = Base.metadata.tables[table_name]
        unique_pairs = {
            tuple(c.name for c in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert columns in unique_pairs
        assert {fk.ondelete for fk in table.foreign_key_constraints} == {"RESTRICT"}


def test_mutable_entities_have_updated_at_with_onupdate() -> None:
    for table_name in ("companies", "crawl_jobs"):
        column = Base.metadata.tables[table_name].c["updated_at"]
        assert column.onupdate is not None


def test_append_only_entities_have_no_updated_at() -> None:
    for table_name in ("domain_observations", "evidence", "decisions", "domain_relationships"):
        assert "updated_at" not in Base.metadata.tables[table_name].c


def test_domain_relationships_has_canonical_order_check() -> None:
    relationships = Base.metadata.tables["domain_relationships"]
    check_expressions = {
        str(constraint.sqltext)
        for constraint in relationships.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert any("domain_a_id < domain_b_id" in expr for expr in check_expressions)


def test_canonical_domain_pair_is_deterministic() -> None:
    low = UUID("00000000-0000-0000-0000-000000000001")
    high = UUID("00000000-0000-0000-0000-000000000002")
    assert canonical_domain_pair(low, high) == (low, high)
    assert canonical_domain_pair(high, low) == (low, high)
    assert canonical_domain_pair(low, high) == canonical_domain_pair(high, low)


def test_canonical_domain_pair_rejects_identical_domains() -> None:
    identical = uuid4()
    with pytest.raises(ValueError):
        canonical_domain_pair(identical, identical)
