"""Add bounded SMS notification tables.

Revision ID: 20260430_0012
Revises: 20260429_0011
Create Date: 2026-04-30 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260430_0012"
down_revision = "20260429_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sms_conversations",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("phone_number", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column(
            "llm_reply_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
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
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_sms_conversations_phone_number",
        "sms_conversations",
        ["phone_number"],
    )
    op.create_index("ix_sms_conversations_run_id", "sms_conversations", ["run_id"])

    op.create_table(
        "sms_messages",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("phone_number", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_message_sid", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["sms_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_sms_messages_conversation_id",
        "sms_messages",
        ["conversation_id"],
    )
    op.create_index("ix_sms_messages_phone_number", "sms_messages", ["phone_number"])
    op.create_index("ix_sms_messages_run_id", "sms_messages", ["run_id"])

    op.create_table(
        "sms_opt_outs",
        sa.Column("phone_number", sa.String(length=16), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "opted_out_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("sms_opt_outs")
    op.drop_index("ix_sms_messages_run_id", table_name="sms_messages")
    op.drop_index("ix_sms_messages_phone_number", table_name="sms_messages")
    op.drop_index("ix_sms_messages_conversation_id", table_name="sms_messages")
    op.drop_table("sms_messages")
    op.drop_index("ix_sms_conversations_run_id", table_name="sms_conversations")
    op.drop_index(
        "ix_sms_conversations_phone_number",
        table_name="sms_conversations",
    )
    op.drop_table("sms_conversations")
