"""Add run execution leases and durable step checkpoints.

Revision ID: 20261104_0025
Revises: 20260522_0024
Create Date: 2026-11-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20261104_0025"
down_revision = "20260522_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("execution_owner_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column(
            "execution_lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_table(
        "run_execution_steps",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_key", sa.String(length=255), nullable=False),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "step_key", name="uq_run_execution_steps_key"),
    )
    op.create_index("ix_run_execution_steps_run_id", "run_execution_steps", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_execution_steps_run_id", table_name="run_execution_steps")
    op.drop_table("run_execution_steps")
    op.drop_column("runs", "execution_lease_expires_at")
    op.drop_column("runs", "execution_owner_token")
