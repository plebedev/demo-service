"""Add label-scoped RAG document chunk storage.

Revision ID: 20260506_0013
Revises: 20260430_0012
Create Date: 2026-05-06 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260506_0013"
down_revision = "20260430_0012"
branch_labels = None
depends_on = None


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def upgrade() -> None:
    dialect_name = _dialect_name()

    if dialect_name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_documents",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_rag_documents_source", "rag_documents", ["source"])
    op.create_index(
        "ix_rag_documents_content_sha256",
        "rag_documents",
        ["content_sha256"],
    )

    op.create_table(
        "rag_labels",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("label_key", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("label_key", name="uq_rag_labels_label_key"),
    )

    op.create_table(
        "rag_document_labels",
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["rag_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["label_id"], ["rag_labels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "label_id"),
    )
    op.create_index(
        "ix_rag_document_labels_label_id",
        "rag_document_labels",
        ["label_id"],
    )

    op.create_table(
        "rag_document_chunks",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("source_location", sa.String(length=255), nullable=True),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["rag_documents.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_rag_document_chunks_document_chunk_index",
        ),
    )
    op.create_index(
        "ix_rag_document_chunks_document_id",
        "rag_document_chunks",
        ["document_id"],
    )

    if dialect_name == "postgresql":
        op.execute(
            "ALTER TABLE rag_document_chunks ADD COLUMN embedding vector(384) NOT NULL"
        )
        op.execute(
            """
            CREATE INDEX ix_rag_document_chunks_embedding_hnsw
            ON rag_document_chunks
            USING hnsw (embedding vector_cosine_ops)
            """
        )
    elif dialect_name == "oracle":
        op.execute("ALTER TABLE rag_document_chunks ADD embedding VECTOR(384, FLOAT32)")
        op.execute("ALTER TABLE rag_document_chunks MODIFY embedding NOT NULL")
        op.execute(
            """
            CREATE VECTOR INDEX ix_rag_doc_chunks_embedding
            ON rag_document_chunks (embedding)
            ORGANIZATION INMEMORY NEIGHBOR GRAPH
            DISTANCE COSINE
            """
        )
    else:
        raise RuntimeError(
            f"Unsupported database dialect for RAG vectors: {dialect_name}"
        )


def downgrade() -> None:
    dialect_name = _dialect_name()
    if dialect_name == "postgresql":
        op.drop_index(
            "ix_rag_document_chunks_embedding_hnsw",
            table_name="rag_document_chunks",
        )
    elif dialect_name == "oracle":
        op.drop_index(
            "ix_rag_doc_chunks_embedding",
            table_name="rag_document_chunks",
        )
    op.drop_index(
        "ix_rag_document_chunks_document_id",
        table_name="rag_document_chunks",
    )
    op.drop_table("rag_document_chunks")
    op.drop_index(
        "ix_rag_document_labels_label_id",
        table_name="rag_document_labels",
    )
    op.drop_table("rag_document_labels")
    op.drop_table("rag_labels")
    op.drop_index(
        "ix_rag_documents_content_sha256",
        table_name="rag_documents",
    )
    op.drop_index("ix_rag_documents_source", table_name="rag_documents")
    op.drop_table("rag_documents")
