"""Extension interfaces for Context Engine domain packs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ArtifactChunk,
    ArtifactType,
    ExtractionResult,
    IngestionRequest,
    PerspectiveBuildContext,
    PerspectiveView,
)


@runtime_checkable
class Extractor(Protocol):
    """Domain extension that derives generic context from artifact chunks."""

    @property
    def id(self) -> str:
        """Stable extractor id."""
        ...

    def extract(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
    ) -> ExtractionResult:
        """Return generic extraction outputs for one artifact."""
        ...


@runtime_checkable
class ArtifactChunker(Protocol):
    """Domain or platform extension that splits artifacts into chunks."""

    @property
    def id(self) -> str:
        """Stable chunker id."""
        ...

    def chunk(self, artifact: Artifact) -> list[ArtifactChunk]:
        """Return source-linked chunks for one artifact."""
        ...


@runtime_checkable
class ArtifactIngestor(Protocol):
    """Extension point for converting external inputs into ingestion requests."""

    @property
    def id(self) -> str:
        """Stable ingestor id."""
        ...

    def ingest(self, payload: dict[str, Any]) -> IngestionRequest:
        """Normalize one input payload into a generic ingestion request."""
        ...


@runtime_checkable
class PerspectiveBuilder(Protocol):
    """Domain extension that can build a materialized perspective."""

    @property
    def id(self) -> str:
        """Stable perspective builder id."""
        ...

    def build(self, context: PerspectiveBuildContext) -> PerspectiveView:
        """Build a generic perspective view."""
        ...


@runtime_checkable
class TaskGenerator(Protocol):
    """Domain extension that can generate generic actionable items."""

    @property
    def id(self) -> str:
        """Stable task generator id."""
        ...

    def generate(self, artifact: Artifact) -> list[ActionableItem]:
        """Generate generic actionable items."""
        ...


class ViewDefinition(BaseModel):
    """Registered view metadata for a domain pack."""

    id: str
    display_name: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class DomainPack:
    """Registered bundle of domain-specific Context Engine extensions."""

    id: str
    display_name: str
    artifact_types: list[ArtifactType] = field(default_factory=list)
    extractors: list[Extractor] = field(default_factory=list)
    perspective_builders: list[PerspectiveBuilder] = field(default_factory=list)
    task_generators: list[TaskGenerator] = field(default_factory=list)
    view_definitions: list[ViewDefinition] = field(default_factory=list)
    chunker: ArtifactChunker | None = None
    ingestors: list[ArtifactIngestor] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
