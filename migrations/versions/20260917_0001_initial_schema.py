"""Create DERE's initial PostgreSQL schema.

Revision ID: 20260917_0001
Revises: None
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMP = sa.DateTime(timezone=True)


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("external_company_id", sa.String(length=128), nullable=False),
        sa.Column("name_raw", sa.String(length=512), nullable=False),
        sa.Column("name_normalized", sa.String(length=512), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
        sa.UniqueConstraint("external_company_id", name="uq_companies_external_company_id"),
    )
    op.create_index("ix_companies_external_company_id", "companies", ["external_company_id"])
    op.create_index("ix_companies_name_normalized", "companies", ["name_normalized"])

    op.create_table(
        "domains",
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("first_seen_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_domains"),
        sa.UniqueConstraint("hostname", name="uq_domains_hostname"),
    )
    op.create_index("ix_domains_hostname", "domains", ["hostname"])

    op.create_table(
        "model_versions",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column(
            "kind",
            _enum("model_version_kind", "RULES", "MODEL", "FEATURE_CONFIGURATION"),
            nullable=False,
        ),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_versions"),
        sa.UniqueConstraint("version", name="uq_model_versions_version"),
    )

    op.create_table(
        "domain_observations",
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("domain_id", UUID, nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("raw_domain", sa.String(length=2048), nullable=False),
        sa.Column(
            "state",
            _enum(
                "domain_state",
                "PRIMARY",
                "SECONDARY",
                "UNRELATED",
                "REVIEW_REQUIRED",
                "UNKNOWN",
                "DEAD",
                "PARKED",
                "REDIRECT",
            ),
            server_default=sa.text("'UNKNOWN'"),
            nullable=False,
        ),
        sa.Column("observed_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_domain_observations_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
            name="fk_domain_observations_domain_id_domains",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_domain_observations"),
    )
    op.create_index("ix_domain_observations_company_id", "domain_observations", ["company_id"])
    op.create_index("ix_domain_observations_domain_id", "domain_observations", ["domain_id"])
    op.create_index("ix_domain_observations_observed_at", "domain_observations", ["observed_at"])

    op.create_table(
        "crawl_jobs",
        sa.Column("domain_id", UUID, nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            _enum("crawl_job_status", "PENDING", "RUNNING", "SUCCEEDED", "FAILED"),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "error_category",
            _enum(
                "crawl_error_category",
                "DNS_ERROR",
                "TIMEOUT",
                "ROBOTS_BLOCKED",
                "HTTP_403",
                "HTTP_429",
                "HTTP_5XX",
                "SSL_ERROR",
                "PARSER_ERROR",
                "JS_RENDER_ERROR",
            ),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=True),
        sa.Column("completed_at", TIMESTAMP, nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
            name="fk_crawl_jobs_domain_id_domains",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crawl_jobs"),
        sa.UniqueConstraint("idempotency_key", name="uq_crawl_jobs_idempotency_key"),
    )
    op.create_index("ix_crawl_jobs_correlation_id", "crawl_jobs", ["correlation_id"])
    op.create_index("ix_crawl_jobs_domain_id", "crawl_jobs", ["domain_id"])

    op.create_table(
        "evidence",
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("domain_a_id", UUID, nullable=True),
        sa.Column("domain_b_id", UUID, nullable=True),
        sa.Column("value", sa.Boolean(), nullable=True),
        sa.Column(
            "strength",
            _enum("evidence_strength", "VERY_STRONG", "STRONG", "SUPPORTING", "WEAK"),
            nullable=False,
        ),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("observed_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_a_id"],
            ["domains.id"],
            name="fk_evidence_domain_a_id_domains",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["domain_b_id"],
            ["domains.id"],
            name="fk_evidence_domain_b_id_domains",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence"),
    )
    op.create_index("ix_evidence_domain_a_id", "evidence", ["domain_a_id"])
    op.create_index("ix_evidence_domain_b_id", "evidence", ["domain_b_id"])
    op.create_index("ix_evidence_reason_code", "evidence", ["reason_code"])
    op.create_index("ix_evidence_evidence_type", "evidence", ["evidence_type"])
    op.create_index("ix_evidence_observed_at", "evidence", ["observed_at"])

    op.create_table(
        "domain_relationships",
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("domain_a_id", UUID, nullable=False),
        sa.Column("domain_b_id", UUID, nullable=False),
        sa.Column("same_organization", sa.Boolean(), nullable=True),
        sa.Column(
            "state",
            _enum(
                "relationship_state", "SAME_ORGANIZATION", "UNRELATED", "REVIEW_REQUIRED", "UNKNOWN"
            ),
            server_default=sa.text("'UNKNOWN'"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_version_id", UUID, nullable=False),
        sa.Column("assessed_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("domain_a_id < domain_b_id", name="canonical_domain_order"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_domain_relationships_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["domain_a_id"],
            ["domains.id"],
            name="fk_domain_relationships_domain_a_id_domains",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["domain_b_id"],
            ["domains.id"],
            name="fk_domain_relationships_domain_b_id_domains",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name="fk_domain_relationships_model_version_id_model_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_domain_relationships"),
    )
    op.create_index("ix_domain_relationships_assessed_at", "domain_relationships", ["assessed_at"])
    op.create_index("ix_domain_relationships_company_id", "domain_relationships", ["company_id"])
    op.create_index("ix_domain_relationships_domain_a_id", "domain_relationships", ["domain_a_id"])
    op.create_index("ix_domain_relationships_domain_b_id", "domain_relationships", ["domain_b_id"])
    op.create_index(
        "ix_domain_relationships_model_version_id", "domain_relationships", ["model_version_id"]
    )

    op.create_table(
        "relationship_evidence",
        sa.Column("relationship_id", UUID, nullable=False),
        sa.Column("evidence_id", UUID, nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name="fk_relationship_evidence_evidence_id_evidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"],
            ["domain_relationships.id"],
            name="fk_relationship_evidence_relationship_id_domain_relationships",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_relationship_evidence"),
        sa.UniqueConstraint(
            "relationship_id",
            "evidence_id",
            name="uq_relationship_evidence_relationship_id",
        ),
    )
    op.create_index(
        "ix_relationship_evidence_evidence_id", "relationship_evidence", ["evidence_id"]
    )
    op.create_index(
        "ix_relationship_evidence_relationship_id", "relationship_evidence", ["relationship_id"]
    )

    op.create_table(
        "decisions",
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("primary_domain_id", UUID, nullable=True),
        sa.Column(
            "status",
            _enum("decision_status", "AUTO_ACCEPT", "AUTO_REJECT", "REVIEW_REQUIRED"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_version_id", UUID, nullable=False),
        sa.Column("outcome_payload", sa.JSON(), nullable=False),
        sa.Column("decided_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_decisions_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name="fk_decisions_model_version_id_model_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["primary_domain_id"],
            ["domains.id"],
            name="fk_decisions_primary_domain_id_domains",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_decisions"),
    )
    op.create_index("ix_decisions_company_id", "decisions", ["company_id"])
    op.create_index("ix_decisions_decided_at", "decisions", ["decided_at"])
    op.create_index("ix_decisions_model_version_id", "decisions", ["model_version_id"])
    op.create_index("ix_decisions_status", "decisions", ["status"])

    op.create_table(
        "decision_evidence",
        sa.Column("decision_id", UUID, nullable=False),
        sa.Column("evidence_id", UUID, nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decisions.id"],
            name="fk_decision_evidence_decision_id_decisions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name="fk_decision_evidence_evidence_id_evidence",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_decision_evidence"),
        sa.UniqueConstraint("decision_id", "evidence_id", name="uq_decision_evidence_decision_id"),
    )
    op.create_index("ix_decision_evidence_decision_id", "decision_evidence", ["decision_id"])
    op.create_index("ix_decision_evidence_evidence_id", "decision_evidence", ["evidence_id"])

    op.create_table(
        "human_reviews",
        sa.Column("decision_id", UUID, nullable=False),
        sa.Column("reviewer", sa.String(length=256), nullable=False),
        sa.Column(
            "decision",
            _enum("review_decision_status", "AUTO_ACCEPT", "AUTO_REJECT", "REVIEW_REQUIRED"),
            nullable=False,
        ),
        sa.Column("corrected_primary_domain_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["corrected_primary_domain_id"],
            ["domains.id"],
            name="fk_human_reviews_corrected_primary_domain_id_domains",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decisions.id"],
            name="fk_human_reviews_decision_id_decisions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_human_reviews"),
    )
    op.create_index("ix_human_reviews_decision_id", "human_reviews", ["decision_id"])

    op.create_table(
        "human_review_secondary_domains",
        sa.Column("human_review_id", UUID, nullable=False),
        sa.Column("domain_id", UUID, nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
            name="fk_human_review_secondary_domains_domain_id_domains",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["human_review_id"],
            ["human_reviews.id"],
            name="fk_human_review_secondary_domains_human_review_id_human_reviews",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_human_review_secondary_domains"),
        sa.UniqueConstraint(
            "human_review_id", "domain_id", name="uq_human_review_secondary_domains_human_review_id"
        ),
    )
    op.create_index(
        "ix_human_review_secondary_domains_domain_id",
        "human_review_secondary_domains",
        ["domain_id"],
    )
    op.create_index(
        "ix_human_review_secondary_domains_human_review_id",
        "human_review_secondary_domains",
        ["human_review_id"],
    )


def downgrade() -> None:
    op.drop_table("human_review_secondary_domains")
    op.drop_table("human_reviews")
    op.drop_table("decision_evidence")
    op.drop_table("decisions")
    op.drop_table("relationship_evidence")
    op.drop_table("domain_relationships")
    op.drop_table("evidence")
    op.drop_table("crawl_jobs")
    op.drop_table("domain_observations")
    op.drop_table("model_versions")
    op.drop_table("domains")
    op.drop_table("companies")
