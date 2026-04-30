"""Add invite fulfillment tracking fields.

Revision ID: 20260429_0011
Revises: 20260428_0010
Create Date: 2026-04-29 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260429_0011"
down_revision = "20260428_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invitation_requests",
        sa.Column(
            "fulfillment_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "invitation_requests",
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invitation_requests",
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invitation_requests",
        sa.Column("fulfillment_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invitation_requests", "fulfillment_error")
    op.drop_column("invitation_requests", "email_sent_at")
    op.drop_column("invitation_requests", "fulfilled_at")
    op.drop_column("invitation_requests", "fulfillment_status")
