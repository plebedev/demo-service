"""SQLAlchemy models for label-scoped RAG document storage."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RagDocument(Base):
    """Source document available to one or more labeled demo flows."""

    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    source: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    metadata_serialized: Mapped[str] = mapped_column(
        "metadata_json", Text(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunks: Mapped[list["RagDocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    labels: Mapped[list["RagLabel"]] = relationship(
        secondary="rag_document_labels",
        back_populates="documents",
    )


class RagLabel(Base):
    """Search label used to scope documents to demo use cases or flows."""

    __tablename__ = "rag_labels"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    label_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    documents: Mapped[list[RagDocument]] = relationship(
        secondary="rag_document_labels",
        back_populates="labels",
    )


class RagDocumentLabel(Base):
    """Join row assigning one label to one document."""

    __tablename__ = "rag_document_labels"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[int] = mapped_column(
        ForeignKey("rag_labels.id", ondelete="CASCADE"), primary_key=True
    )


class RagDocumentChunk(Base):
    """Text chunk for similarity search.

    The database table also has an `embedding` vector column. Vector operations
    are handled with explicit dialect SQL so the service can support pgvector
    locally and Oracle 23ai in production without a Python-only type dependency.
    """

    __tablename__ = "rag_document_chunks"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=True)
    source_location: Mapped[str] = mapped_column(String(255), nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text(), nullable=False)
    metadata_serialized: Mapped[str] = mapped_column(
        "metadata_json", Text(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[RagDocument] = relationship(back_populates="chunks")
