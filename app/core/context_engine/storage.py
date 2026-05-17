"""Storage abstractions and in-memory adapter for Context Engine records."""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ArtifactChunk,
    ContextEntity,
    ContextRelationship,
    ContextSignal,
    OwnerType,
)


class ContextRepository(Protocol):
    """Repository contract for Context Engine persistence."""

    def store_artifact(self, artifact: Artifact) -> Artifact:
        """Persist one artifact."""
        ...

    def store_chunks(self, chunks: list[ArtifactChunk]) -> list[ArtifactChunk]:
        """Persist artifact chunks."""
        ...

    def store_entities(self, entities: list[ContextEntity]) -> list[ContextEntity]:
        """Persist context entities."""
        ...

    def store_relationships(
        self, relationships: list[ContextRelationship]
    ) -> list[ContextRelationship]:
        """Persist context relationships."""
        ...

    def store_signals(self, signals: list[ContextSignal]) -> list[ContextSignal]:
        """Persist context signals."""
        ...

    def store_actionable_items(
        self, items: list[ActionableItem]
    ) -> list[ActionableItem]:
        """Persist actionable items."""
        ...

    def list_signals(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextSignal]:
        """Return signals visible in one owner namespace."""
        ...

    def list_actionable_items(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ActionableItem]:
        """Return actionable items visible in one owner namespace."""
        ...


class InMemoryContextRepository:
    """Process-local repository used until durable storage is introduced."""

    def __init__(self) -> None:
        self.artifacts: dict[str, Artifact] = {}
        self.chunks: dict[str, ArtifactChunk] = {}
        self.entities: dict[str, ContextEntity] = {}
        self.relationships: dict[str, ContextRelationship] = {}
        self.signals: dict[str, ContextSignal] = {}
        self.actionable_items: dict[str, ActionableItem] = {}
        self._signal_index: dict[tuple[str, OwnerType, str], list[str]] = defaultdict(
            list
        )
        self._task_index: dict[tuple[str, OwnerType, str], list[str]] = defaultdict(
            list
        )

    def store_artifact(self, artifact: Artifact) -> Artifact:
        """Store one artifact in memory."""
        self.artifacts[artifact.id] = artifact
        return artifact

    def store_chunks(self, chunks: list[ArtifactChunk]) -> list[ArtifactChunk]:
        """Store chunks in memory."""
        for chunk in chunks:
            self.chunks[chunk.id] = chunk
        return chunks

    def store_entities(self, entities: list[ContextEntity]) -> list[ContextEntity]:
        """Store entities in memory."""
        for entity in entities:
            self.entities[entity.id] = entity
        return entities

    def store_relationships(
        self, relationships: list[ContextRelationship]
    ) -> list[ContextRelationship]:
        """Store relationships in memory."""
        for relationship in relationships:
            self.relationships[relationship.id] = relationship
        return relationships

    def store_signals(self, signals: list[ContextSignal]) -> list[ContextSignal]:
        """Store signals in memory."""
        for signal in signals:
            self.signals[signal.id] = signal
        return signals

    def store_actionable_items(
        self, items: list[ActionableItem]
    ) -> list[ActionableItem]:
        """Store actionable items in memory."""
        for item in items:
            self.actionable_items[item.id] = item
        return items

    def index_artifact_outputs(
        self,
        *,
        artifact: Artifact,
        signals: list[ContextSignal],
        actionable_items: list[ActionableItem],
    ) -> None:
        """Index owner-scoped outputs for simple lookup APIs."""
        key = (artifact.domain_id, artifact.owner_type, artifact.owner_id)
        self._signal_index[key].extend(signal.id for signal in signals)
        self._task_index[key].extend(item.id for item in actionable_items)

    def list_signals(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextSignal]:
        """Return owner-scoped signals."""
        key = (domain_id, owner_type, owner_id)
        return [self.signals[signal_id] for signal_id in self._signal_index[key]]

    def list_actionable_items(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ActionableItem]:
        """Return owner-scoped actionable items."""
        key = (domain_id, owner_type, owner_id)
        return [self.actionable_items[item_id] for item_id in self._task_index[key]]
