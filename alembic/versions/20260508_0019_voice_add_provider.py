"""voice: drop voice_id, add voice_provider

Revision ID: 20260508_0019
Revises: 20260508_0018
Create Date: 2026-05-08

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260508_0019"
down_revision = "20260508_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop voice_id (added in 0018, now superseded); add voice_provider."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("voice_experience_configs")}

    if "voice_id" in existing:
        op.drop_column("voice_experience_configs", "voice_id")

    if "voice_provider" not in existing:
        op.add_column(
            "voice_experience_configs",
            sa.Column("voice_provider", sa.String(32), nullable=True),
        )


def downgrade() -> None:
    """Reverse: drop voice_provider, restore voice_id."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("voice_experience_configs")}

    if "voice_provider" in existing:
        op.drop_column("voice_experience_configs", "voice_provider")

    if "voice_id" not in existing:
        op.add_column(
            "voice_experience_configs",
            sa.Column("voice_id", sa.String(64), nullable=True),
        )
