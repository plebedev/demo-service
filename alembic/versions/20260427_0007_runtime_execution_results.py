"""Add runtime execution result storage.

Revision ID: 20260427_0007
Revises: 20260427_0006
Create Date: 2026-04-27 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260427_0007"
down_revision = "20260427_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("post_processor_results_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "run_events",
        sa.Column("status", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run_events", "status")
    op.drop_column("runs", "post_processor_results_json")
