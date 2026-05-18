"""SQLAlchemy models for generic Context Engine persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContextArtifactRecord(Base):
    """Persisted generic source artifact."""

    __tablename__ = "context_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    artifact_type_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_uri: Mapped[str] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ContextArtifactChunkRecord(Base):
    """Persisted generic source artifact chunk."""

    __tablename__ = "context_artifact_chunks"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "chunk_index",
            name="uq_context_artifact_chunks_artifact_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("context_artifacts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    source_link_json: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)


class ContextEntityRecord(Base):
    """Persisted generic extracted entity."""

    __tablename__ = "context_entities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_links_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)


class ContextRelationshipRecord(Base):
    """Persisted generic extracted relationship."""

    __tablename__ = "context_relationships"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_links_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)


class ContextSignalRecord(Base):
    """Persisted generic context signal."""

    __tablename__ = "context_signals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=True)
    source_links_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)


class ContextActionableItemRecord(Base):
    """Persisted generic actionable item."""

    __tablename__ = "context_actionable_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    item_type: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    readiness_status: Mapped[str] = mapped_column(String(64), nullable=False)
    source_links_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)


class ContextSourceLinkRecord(Base):
    """Persisted source-link audit row for derived context."""

    __tablename__ = "context_source_links"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    artifact_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("context_artifacts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=True)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=True)
    label: Mapped[str] = mapped_column(String(512), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=True)
