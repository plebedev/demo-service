"""Add workflow key and run event audit scaffolding.

Revision ID: 20260427_0006
Revises: 20260427_0005
Create Date: 2026-04-27 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260427_0006"
down_revision = "20260427_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "workflow_key",
            sa.String(length=128),
            nullable=False,
            server_default="messy-notes-v1",
        ),
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("agent_role", sa.String(length=128), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("tool_arguments_json", sa.Text(), nullable=True),
        sa.Column("tool_result_json", sa.Text(), nullable=True),
        sa.Column("handoff_source_role", sa.String(length=128), nullable=True),
        sa.Column("handoff_target_role", sa.String(length=128), nullable=True),
        sa.Column("post_processor_key", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_run_events_run_id", table_name="run_events")
    op.drop_table("run_events")
    op.drop_column("runs", "workflow_key")
