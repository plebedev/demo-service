"""Add M6 follow-up and notification state.

Revision ID: 20260428_0008
Revises: 20260427_0007
Create Date: 2026-04-28 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260428_0008"
down_revision = "20260427_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("follow_up_response_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("notification_preference_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "notification_preference_json")
    op.drop_column("runs", "follow_up_response_json")
