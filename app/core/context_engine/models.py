"""Domain-neutral Context Engine data contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def new_context_id(prefix: str) -> str:
    """Return a stable string id for in-memory context records."""
    return f"{prefix}_{uuid4().hex}"


class OwnerType(StrEnum):
    """Generic owner namespace for context records."""

    INVITATION_CODE = "invitation_code"
    SYSTEM = "system"


class ReadinessStatus(StrEnum):
    """Generic readiness state for actionable context items."""

    READY = "ready"
    NEEDS_INPUT = "needs_input"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class SourceLink(BaseModel):
    """Pointer from derived context back to source artifact text."""

    artifact_id: str
    chunk_id: str | None = None
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    label: str | None = None
    excerpt: str | None = None


class EvidenceLink(BaseModel):
    """Evidence pointer used by views and task outputs."""

    source: SourceLink
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = None


class ArtifactType(BaseModel):
    """Domain-registered artifact type definition."""

    id: str
    display_name: str
    description: str | None = None
    accepted_mime_types: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Artifact(BaseModel):
    """Ingested source artifact."""

    id: str = Field(default_factory=lambda: new_context_id("art"))
    domain_id: str
    artifact_type_id: str
    owner_type: OwnerType
    owner_id: str
    title: str | None = None
    text: str
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArtifactChunk(BaseModel):
    """Chunk of one source artifact."""

    id: str = Field(default_factory=lambda: new_context_id("chunk"))
    artifact_id: str
    chunk_index: int = Field(ge=0)
    text: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    source_link: SourceLink
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextEntity(BaseModel):
    """Generic extracted entity."""

    id: str = Field(default_factory=lambda: new_context_id("entity"))
    entity_type: str
    name: str
    source_links: list[SourceLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextRelationship(BaseModel):
    """Generic relationship between two context entities."""

    id: str = Field(default_factory=lambda: new_context_id("rel"))
    relationship_type: str
    source_entity_id: str
    target_entity_id: str
    source_links: list[SourceLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextSignal(BaseModel):
    """Generic signal derived from artifacts or extracted context."""

    id: str = Field(default_factory=lambda: new_context_id("signal"))
    signal_type: str
    label: str
    value: str | int | float | bool | None = None
    source_links: list[SourceLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ViewSection(BaseModel):
    """Section inside a generated perspective view."""

    id: str
    title: str
    content: str | None = None
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PerspectiveView(BaseModel):
    """Generic materialized view built from domain context."""

    id: str = Field(default_factory=lambda: new_context_id("view"))
    view_definition_id: str
    title: str
    sections: list[ViewSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionableItem(BaseModel):
    """Generic task/action recommendation derived from context."""

    id: str = Field(default_factory=lambda: new_context_id("item"))
    item_type: str
    title: str
    description: str | None = None
    readiness_status: ReadinessStatus = ReadinessStatus.UNKNOWN
    source_links: list[SourceLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """Generic output from one extractor."""

    entities: list[ContextEntity] = Field(default_factory=list)
    relationships: list[ContextRelationship] = Field(default_factory=list)
    signals: list[ContextSignal] = Field(default_factory=list)
    actionable_items: list[ActionableItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionRequest(BaseModel):
    """Input required to ingest one artifact."""

    domain_id: str
    artifact_type_id: str
    owner_type: OwnerType
    owner_id: str
    text: str
    title: str | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    """Summary returned after an artifact ingestion run."""

    artifact: Artifact
    chunks: list[ArtifactChunk]
    entities: list[ContextEntity]
    relationships: list[ContextRelationship]
    signals: list[ContextSignal]
    actionable_items: list[ActionableItem]
    extractor_ids: list[str]
