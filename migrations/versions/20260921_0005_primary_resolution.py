"""Add primary-domain resolution tables for Phase 6.

Adds ``primary_resolutions`` (per same-org group result, separate from the final
CPT ``decisions`` table), ``primary_domain_scores`` (per-domain score and
designation), and ``primary_resolution_evidence`` (relational evidence
traceability). No existing table is modified. Fully reversible.

Revision ID: 20260921_0005
Revises: 20260920_0004
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_0005"
down_revision: str | None = "20260920_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMP = sa.DateTime(timezone=True)


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "primary_resolutions",
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("group_key", sa.String(length=64), nullable=False),
        sa.Column("model_version_id", UUID, nullable=False),
        sa.Column(
            "status",
            _enum("primary_resolution_status", "RESOLVED", "REVIEW_REQUIRED"),
            nullable=False,
        ),
        sa.Column("primary_domain_id", UUID, nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("confidence_band", sa.String(length=16), nullable=True),
        sa.Column("margin", sa.Float(), nullable=True),
        sa.Column("domain_ids", sa.JSON(), nullable=False),
        sa.Column("conflicts", sa.JSON(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_primary_resolutions_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name="fk_primary_resolutions_model_version_id_model_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["primary_domain_id"],
            ["domains.id"],
            name="fk_primary_resolutions_primary_domain_id_domains",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_primary_resolutions"),
        sa.UniqueConstraint(
            "company_id",
            "group_key",
            "model_version_id",
            name="uq_primary_resolutions_company_id",
        ),
    )
    op.create_index("ix_primary_resolutions_company_id", "primary_resolutions", ["company_id"])
    op.create_index("ix_primary_resolutions_group_key", "primary_resolutions", ["group_key"])
    op.create_index(
        "ix_primary_resolutions_model_version_id", "primary_resolutions", ["model_version_id"]
    )
    op.create_index(
        "ix_primary_resolutions_primary_domain_id", "primary_resolutions", ["primary_domain_id"]
    )
    op.create_index("ix_primary_resolutions_status", "primary_resolutions", ["status"])

    op.create_table(
        "primary_domain_scores",
        sa.Column("resolution_id", UUID, nullable=False),
        sa.Column("domain_id", UUID, nullable=False),
        sa.Column("primary_score", sa.Float(), nullable=False),
        sa.Column(
            "designation",
            _enum("primary_domain_designation", "PRIMARY", "SECONDARY", "UNRESOLVED"),
            nullable=False,
        ),
        sa.Column("reason_codes", sa.JSON(), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
            name="fk_primary_domain_scores_domain_id_domains",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolution_id"],
            ["primary_resolutions.id"],
            name="fk_primary_domain_scores_resolution_id_primary_resolutions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_primary_domain_scores"),
        sa.UniqueConstraint(
            "resolution_id", "domain_id", name="uq_primary_domain_scores_resolution_id"
        ),
    )
    op.create_index("ix_primary_domain_scores_domain_id", "primary_domain_scores", ["domain_id"])
    op.create_index(
        "ix_primary_domain_scores_resolution_id", "primary_domain_scores", ["resolution_id"]
    )

    op.create_table(
        "primary_resolution_evidence",
        sa.Column("resolution_id", UUID, nullable=False),
        sa.Column("evidence_id", UUID, nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name="fk_primary_resolution_evidence_evidence_id_evidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolution_id"],
            ["primary_resolutions.id"],
            name="fk_primary_resolution_evidence_resolution_id_primary_re_d474",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_primary_resolution_evidence"),
        sa.UniqueConstraint(
            "resolution_id",
            "evidence_id",
            name="uq_primary_resolution_evidence_resolution_id",
        ),
    )
    op.create_index(
        "ix_primary_resolution_evidence_evidence_id",
        "primary_resolution_evidence",
        ["evidence_id"],
    )
    op.create_index(
        "ix_primary_resolution_evidence_resolution_id",
        "primary_resolution_evidence",
        ["resolution_id"],
    )


def downgrade() -> None:
    op.drop_table("primary_resolution_evidence")
    op.drop_table("primary_domain_scores")
    op.drop_table("primary_resolutions")
