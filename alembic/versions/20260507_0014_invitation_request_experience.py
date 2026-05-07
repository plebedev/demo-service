"""Add requested experience to invitation requests.

Revision ID: 20260507_0014
Revises: 20260506_0013
Create Date: 2026-05-07 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260507_0014"
down_revision = "20260506_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invitation_requests",
        sa.Column("label", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invitation_requests", "label")
