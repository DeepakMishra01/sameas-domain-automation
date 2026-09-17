"""Extend the schema for safe domain observation (Phase 3).

Adds observation attribution and factual error classification to
``domain_observations`` and relational traceability from ``evidence`` to the
observation that produced it. No table is redesigned; historical rows are
preserved.

Revision ID: 20260918_0002
Revises: 20260917_0001
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260918_0002"
down_revision: str | None = "20260917_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

OBSERVATION_ERROR_VALUES: tuple[str, ...] = (
    "DNS_ERROR",
    "TIMEOUT",
    "ROBOTS_BLOCKED",
    "HTTP_403",
    "HTTP_429",
    "HTTP_4XX",
    "HTTP_5XX",
    "SSL_ERROR",
    "CONNECTION_ERROR",
    "PARSER_ERROR",
    "RESPONSE_TOO_LARGE",
    "REDIRECT_LIMIT",
    "SSRF_BLOCKED",
)


def _error_enum() -> sa.Enum:
    return sa.Enum(
        *OBSERVATION_ERROR_VALUES,
        name="observation_error_category",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    op.add_column(
        "domain_observations",
        sa.Column("collector_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "domain_observations",
        sa.Column("error_category", _error_enum(), nullable=True),
    )
    op.add_column(
        "domain_observations",
        sa.Column("error_detail", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_domain_observations_collector_version",
        "domain_observations",
        ["collector_version"],
    )

    # Factual observation evidence asserts no validated weight.
    op.alter_column("evidence", "strength", existing_type=sa.String(length=11), nullable=True)
    op.add_column("evidence", sa.Column("observation_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_evidence_observation_id_domain_observations",
        "evidence",
        "domain_observations",
        ["observation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_evidence_observation_id", "evidence", ["observation_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_observation_id", table_name="evidence")
    op.drop_constraint(
        "fk_evidence_observation_id_domain_observations", "evidence", type_="foreignkey"
    )
    op.drop_column("evidence", "observation_id")
    op.alter_column("evidence", "strength", existing_type=sa.String(length=11), nullable=False)

    op.drop_index("ix_domain_observations_collector_version", table_name="domain_observations")
    # Pass the short constraint token; the metadata naming convention expands it
    # to ck_domain_observations_observation_error_category.
    op.drop_constraint(
        "observation_error_category",
        "domain_observations",
        type_="check",
    )
    op.drop_column("domain_observations", "error_detail")
    op.drop_column("domain_observations", "error_category")
    op.drop_column("domain_observations", "collector_version")
