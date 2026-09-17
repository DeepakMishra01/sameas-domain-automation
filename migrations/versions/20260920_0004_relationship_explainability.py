"""Add explainability columns to domain_relationships for Phase 5 matching.

Adds nullable ``reason_codes`` and ``match_features`` JSON columns so a persisted
same-organization assessment records which signals fired and the deterministic
pairwise feature audit. No existing column is modified. Fully reversible.

Revision ID: 20260920_0004
Revises: 20260919_0003
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0004"
down_revision: str | None = "20260919_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("domain_relationships", sa.Column("reason_codes", sa.JSON(), nullable=True))
    op.add_column("domain_relationships", sa.Column("match_features", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("domain_relationships", "match_features")
    op.drop_column("domain_relationships", "reason_codes")
