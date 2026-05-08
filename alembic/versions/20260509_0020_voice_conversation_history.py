"""voice: add voice_conversation_records table for conversation history.

Revision ID: 20260509_0020
Revises: 20260508_0019
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260509_0020"
down_revision = "20260508_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "voice_conversation_records" not in existing_tables:
        op.create_table(
            "voice_conversation_records",
            sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
            sa.Column("experience_id", sa.String(128), nullable=False),
            sa.Column("call_sid", sa.String(255), nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("voice", sa.String(128), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("input_audio_seconds", sa.Float(), nullable=True),
            sa.Column("output_audio_seconds", sa.Float(), nullable=True),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
            sa.Column(
                "transcript_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("call_sid", name="uq_voice_conversation_records_call_sid"),
        )
        op.create_index(
            "ix_voice_conversation_records_experience_id",
            "voice_conversation_records",
            ["experience_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "voice_conversation_records" in existing_tables:
        op.drop_index(
            "ix_voice_conversation_records_experience_id",
            table_name="voice_conversation_records",
        )
        op.drop_table("voice_conversation_records")
