"""Add the observation_features table for Phase 4 feature extraction.

Append-only, versioned feature snapshots derived deterministically from
persisted observations. No existing table is modified. Fully reversible.

Revision ID: 20260919_0003
Revises: 20260918_0002
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260919_0003"
down_revision: str | None = "20260918_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "observation_features",
        sa.Column("observation_id", UUID, nullable=False),
        sa.Column("domain_id", UUID, nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
            name="fk_observation_features_domain_id_domains",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["domain_observations.id"],
            name="fk_observation_features_observation_id_domain_observations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_observation_features"),
        sa.UniqueConstraint(
            "observation_id",
            "feature_version",
            name="uq_observation_features_observation_id",
        ),
    )
    op.create_index("ix_observation_features_domain_id", "observation_features", ["domain_id"])
    op.create_index(
        "ix_observation_features_feature_version", "observation_features", ["feature_version"]
    )
    op.create_index(
        "ix_observation_features_observation_id", "observation_features", ["observation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_observation_features_observation_id", table_name="observation_features")
    op.drop_index("ix_observation_features_feature_version", table_name="observation_features")
    op.drop_index("ix_observation_features_domain_id", table_name="observation_features")
    op.drop_table("observation_features")
