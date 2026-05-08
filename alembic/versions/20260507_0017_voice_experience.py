"""Add voice experience config and persona tables.

Revision ID: 20260507_0017
Revises: 20260507_0016
Create Date: 2026-05-07 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260507_0017"
down_revision = "20260507_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "voice_experience_configs" not in existing:
        op.create_table(
            "voice_experience_configs",
            sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
            sa.Column("experience_id", sa.String(length=64), nullable=False),
            sa.Column("voice_name", sa.String(length=128), nullable=False),
            sa.Column("synthesized_greeting", sa.Text(), nullable=True),
            sa.Column("greeting_synced_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.UniqueConstraint(
                "experience_id", name="uq_voice_experience_configs_experience_id"
            ),
        )
        op.create_index(
            "ix_voice_experience_configs_experience_id",
            "voice_experience_configs",
            ["experience_id"],
        )

    if "voice_personas" not in existing:
        op.create_table(
            "voice_personas",
            sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
            sa.Column("experience_id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("name_key", sa.String(length=255), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=False),
            sa.Column("capabilities_json", sa.Text(), nullable=True),
            sa.Column("tool_config_json", sa.Text(), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
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
            sa.UniqueConstraint(
                "experience_id",
                "name_key",
                "is_active",
                name="uq_voice_personas_experience_name_active",
            ),
        )
        op.create_index(
            "ix_voice_personas_experience_id",
            "voice_personas",
            ["experience_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_personas_experience_id",
        table_name="voice_personas",
        if_exists=True,
    )
    op.drop_table("voice_personas", if_exists=True)
    op.drop_index(
        "ix_voice_experience_configs_experience_id",
        table_name="voice_experience_configs",
        if_exists=True,
    )
    op.drop_table("voice_experience_configs", if_exists=True)
