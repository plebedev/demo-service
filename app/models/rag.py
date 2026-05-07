"""SQLAlchemy models for label-scoped RAG document storage."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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


class RagPersona(Base):
    """Tenant-scoped assistant persona for the RAG demo."""

    __tablename__ = "rag_personas"
    __table_args__ = (
        UniqueConstraint(
            "invitation_code_id",
            "name_key",
            "is_active",
            name="uq_rag_personas_invitation_name_active",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    invitation_code_id: Mapped[int] = mapped_column(
        ForeignKey("invitation_codes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_key: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[str] = mapped_column(Text(), nullable=False)
    capabilities_serialized: Mapped[str] = mapped_column(
        "capabilities_json", Text(), nullable=True
    )
    tool_config_serialized: Mapped[str] = mapped_column(
        "tool_config_json", Text(), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    documents: Mapped[list["RagPersonaDocument"]] = relationship(
        back_populates="persona", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["RagConversation"]] = relationship(
        back_populates="persona"
    )


class RagPersonaDocument(Base):
    """Join row linking a persona to a reusable source document."""

    __tablename__ = "rag_persona_documents"

    persona_id: Mapped[int] = mapped_column(
        ForeignKey("rag_personas.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(512), nullable=True)
    metadata_serialized: Mapped[str] = mapped_column(
        "metadata_json", Text(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    persona: Mapped[RagPersona] = relationship(back_populates="documents")
    document: Mapped[RagDocument] = relationship()


class RagConversation(Base):
    """Stored RAG conversation scoped to one invitation namespace."""

    __tablename__ = "rag_conversations"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    invitation_code_id: Mapped[int] = mapped_column(
        ForeignKey("invitation_codes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persona_id: Mapped[int] = mapped_column(
        ForeignKey("rag_personas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    persona: Mapped["RagPersona"] = relationship(back_populates="conversations")
    messages: Mapped[list["RagMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class RagMessage(Base):
    """Stored message for a future RAG chat conversation."""

    __tablename__ = "rag_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "turn_index",
            name="uq_rag_messages_conversation_turn_index",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("rag_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_serialized: Mapped[str] = mapped_column(
        "metadata_json", Text(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[RagConversation] = relationship(back_populates="messages")


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
