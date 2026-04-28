"""Add invitation request intake table.

Revision ID: 20260428_0009
Revises: 20260428_0008
Create Date: 2026-04-28 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260428_0009"
down_revision = "20260428_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitation_requests",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="submitted",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_invitation_requests_email", "invitation_requests", ["email"])


def downgrade() -> None:
    op.drop_index("ix_invitation_requests_email", table_name="invitation_requests")
    op.drop_table("invitation_requests")
