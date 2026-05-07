"""Add tenant-scoped RAG personas and conversation storage.

Revision ID: 20260507_0015
Revises: 20260507_0014
Create Date: 2026-05-07 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260507_0015"
down_revision = "20260507_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_personas",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("invitation_code_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["invitation_code_id"],
            ["invitation_codes.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "invitation_code_id",
            "name_key",
            "is_active",
            name="uq_rag_personas_invitation_name_active",
        ),
    )
    op.create_index(
        "ix_rag_personas_invitation_code_id",
        "rag_personas",
        ["invitation_code_id"],
    )

    op.create_table(
        "rag_persona_documents",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["rag_personas.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["rag_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("persona_id", "document_id"),
    )
    op.create_index(
        "ix_rag_persona_documents_document_id",
        "rag_persona_documents",
        ["document_id"],
    )

    op.create_table(
        "rag_conversations",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("invitation_code_id", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
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
        sa.ForeignKeyConstraint(
            ["invitation_code_id"],
            ["invitation_codes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["rag_personas.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_rag_conversations_invitation_code_id",
        "rag_conversations",
        ["invitation_code_id"],
    )
    op.create_index(
        "ix_rag_conversations_persona_id",
        "rag_conversations",
        ["persona_id"],
    )

    op.create_table(
        "rag_messages",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["rag_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "turn_index",
            name="uq_rag_messages_conversation_turn_index",
        ),
    )
    op.create_index(
        "ix_rag_messages_conversation_id",
        "rag_messages",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_messages_conversation_id", table_name="rag_messages")
    op.drop_table("rag_messages")
    op.drop_index(
        "ix_rag_conversations_persona_id",
        table_name="rag_conversations",
    )
    op.drop_index(
        "ix_rag_conversations_invitation_code_id",
        table_name="rag_conversations",
    )
    op.drop_table("rag_conversations")
    op.drop_index(
        "ix_rag_persona_documents_document_id",
        table_name="rag_persona_documents",
    )
    op.drop_table("rag_persona_documents")
    op.drop_index(
        "ix_rag_personas_invitation_code_id",
        table_name="rag_personas",
    )
    op.drop_table("rag_personas")
