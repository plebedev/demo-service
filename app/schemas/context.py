"""Pydantic schemas for generic Context Engine APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ArtifactChunk,
    ArtifactType,
    ContextEntity,
    ContextRelationship,
    ContextSignal,
    PerspectiveView,
)


class ExtensionSummaryResponse(BaseModel):
    """Public metadata for a registered runtime extension."""

    id: str


class ViewDefinitionResponse(BaseModel):
    """Public metadata for a registered view definition."""

    id: str
    display_name: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DomainSummaryResponse(BaseModel):
    """Public summary of a registered domain pack."""

    id: str
    display_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DomainDetailResponse(DomainSummaryResponse):
    """Public details for a registered domain pack."""

    artifact_types: list[ArtifactType]
    perspectives: list[ExtensionSummaryResponse]
    views: list[ViewDefinitionResponse]


class DomainListResponse(BaseModel):
    """Registered domain pack list."""

    domains: list[DomainSummaryResponse]


class ContextArtifactCreateRequest(BaseModel):
    """API request to ingest one generic artifact."""

    artifact_type_id: str
    text: str
    title: str | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextArtifactIngestResponse(BaseModel):
    """API response for generic artifact ingestion."""

    artifact: Artifact
    chunks: list[ArtifactChunk]
    entities: list[ContextEntity]
    relationships: list[ContextRelationship]
    signals: list[ContextSignal]
    actionable_items: list[ActionableItem]
    extractor_ids: list[str]


class ContextSignalListResponse(BaseModel):
    """Owner-scoped context signal list."""

    signals: list[ContextSignal]


class ActionableItemListResponse(BaseModel):
    """Owner-scoped actionable item list."""

    tasks: list[ActionableItem]


class PerspectiveViewResponse(BaseModel):
    """Owner-scoped materialized perspective view."""

    view: PerspectiveView
