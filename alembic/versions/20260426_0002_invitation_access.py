"""Add invitation access tables

Revision ID: 20260426_0002
Revises: 20260419_0001
Create Date: 2026-04-26 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260426_0002"
down_revision = "20260419_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitation_codes",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "invitation_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("invitation_code_id", sa.Integer(), nullable=False),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("token_id", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["invitation_code_id"], ["invitation_codes.id"]),
    )


def downgrade() -> None:
    op.drop_table("invitation_redemptions")
    op.drop_table("invitation_codes")
