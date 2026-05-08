"""Add voice_id column to voice_experience_configs.

Revision ID: 20260508_0018
Revises: 20260507_0017
Create Date: 2026-05-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260508_0018"
down_revision = "20260507_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("voice_experience_configs")}

    if "voice_id" not in existing_cols:
        op.add_column(
            "voice_experience_configs",
            sa.Column("voice_id", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("voice_experience_configs", "voice_id")
