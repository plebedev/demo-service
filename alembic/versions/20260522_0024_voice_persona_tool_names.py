"""Add explicit voice persona tool names.

Revision ID: 20260522_0024
Revises: 20260518_0023
Create Date: 2026-05-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260522_0024"
down_revision = "20260518_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("voice_personas")
    }
    if "tool_names_json" not in columns:
        op.add_column(
            "voice_personas",
            sa.Column("tool_names_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("voice_personas")
    }
    if "tool_names_json" in columns:
        op.drop_column("voice_personas", "tool_names_json")
