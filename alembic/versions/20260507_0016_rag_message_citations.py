"""Add RAG message citation storage.

Revision ID: 20260507_0016
Revises: 20260507_0015
Create Date: 2026-05-07 15:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260507_0016"
down_revision = "20260507_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_message_citations",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["rag_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["rag_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["rag_document_chunks.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_rag_message_citations_message_id",
        "rag_message_citations",
        ["message_id"],
    )
    op.create_index(
        "ix_rag_message_citations_document_id",
        "rag_message_citations",
        ["document_id"],
    )
    op.create_index(
        "ix_rag_message_citations_chunk_id",
        "rag_message_citations",
        ["chunk_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_message_citations_chunk_id", table_name="rag_message_citations")
    op.drop_index(
        "ix_rag_message_citations_document_id",
        table_name="rag_message_citations",
    )
    op.drop_index(
        "ix_rag_message_citations_message_id",
        table_name="rag_message_citations",
    )
    op.drop_table("rag_message_citations")
