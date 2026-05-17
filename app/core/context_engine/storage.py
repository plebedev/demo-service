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
    SourceLink,
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

    def store_source_links(self, links: list[SourceLink]) -> list[SourceLink]:
        """Persist source links for provenance queries or audits."""
        ...

    def index_artifact_outputs(
        self,
        *,
        artifact: Artifact,
        signals: list[ContextSignal],
        actionable_items: list[ActionableItem],
    ) -> None:
        """Index or associate outputs with their source artifact owner."""
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

    def list_artifacts(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[Artifact]:
        """Return artifacts visible in one owner namespace."""
        ...

    def list_chunks_for_artifacts(self, artifact_ids: list[str]) -> list[ArtifactChunk]:
        """Return chunks for the provided artifact ids."""
        ...

    def list_entities(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextEntity]:
        """Return entities visible in one owner namespace."""
        ...

    def list_relationships(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextRelationship]:
        """Return relationships visible in one owner namespace."""
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
        self.source_links: list[SourceLink] = []
        self._artifact_index: dict[tuple[str, OwnerType, str], list[str]] = defaultdict(
            list
        )
        self._entity_index: dict[tuple[str, OwnerType, str], list[str]] = defaultdict(
            list
        )
        self._relationship_index: dict[tuple[str, OwnerType, str], list[str]] = (
            defaultdict(list)
        )
        self._signal_index: dict[tuple[str, OwnerType, str], list[str]] = defaultdict(
            list
        )
        self._task_index: dict[tuple[str, OwnerType, str], list[str]] = defaultdict(
            list
        )

    def store_artifact(self, artifact: Artifact) -> Artifact:
        """Store one artifact in memory."""
        self.artifacts[artifact.id] = artifact
        key = (artifact.domain_id, artifact.owner_type, artifact.owner_id)
        self._artifact_index[key].append(artifact.id)
        return artifact

    def store_chunks(self, chunks: list[ArtifactChunk]) -> list[ArtifactChunk]:
        """Store chunks in memory."""
        for chunk in chunks:
            self.chunks[chunk.id] = chunk
            self.store_source_links([chunk.source_link])
        return chunks

    def store_entities(self, entities: list[ContextEntity]) -> list[ContextEntity]:
        """Store entities in memory."""
        for entity in entities:
            self.entities[entity.id] = entity
            for source_link in entity.source_links:
                artifact = self.artifacts.get(source_link.artifact_id)
                if artifact is not None:
                    key = (artifact.domain_id, artifact.owner_type, artifact.owner_id)
                    self._entity_index[key].append(entity.id)
            self.store_source_links(entity.source_links)
        return entities

    def store_relationships(
        self, relationships: list[ContextRelationship]
    ) -> list[ContextRelationship]:
        """Store relationships in memory."""
        for relationship in relationships:
            self.relationships[relationship.id] = relationship
            for source_link in relationship.source_links:
                artifact = self.artifacts.get(source_link.artifact_id)
                if artifact is not None:
                    key = (artifact.domain_id, artifact.owner_type, artifact.owner_id)
                    self._relationship_index[key].append(relationship.id)
            self.store_source_links(relationship.source_links)
        return relationships

    def store_signals(self, signals: list[ContextSignal]) -> list[ContextSignal]:
        """Store signals in memory."""
        for signal in signals:
            self.signals[signal.id] = signal
            self.store_source_links(signal.source_links)
        return signals

    def store_actionable_items(
        self, items: list[ActionableItem]
    ) -> list[ActionableItem]:
        """Store actionable items in memory."""
        for item in items:
            self.actionable_items[item.id] = item
            self.store_source_links(item.source_links)
        return items

    def store_source_links(self, links: list[SourceLink]) -> list[SourceLink]:
        """Store source links in memory."""
        self.source_links.extend(links)
        return links

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

    def list_artifacts(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[Artifact]:
        """Return owner-scoped artifacts."""
        key = (domain_id, owner_type, owner_id)
        return [
            self.artifacts[artifact_id] for artifact_id in self._artifact_index[key]
        ]

    def list_chunks_for_artifacts(self, artifact_ids: list[str]) -> list[ArtifactChunk]:
        """Return chunks for artifacts in insertion order."""
        artifact_id_set = set(artifact_ids)
        return [
            chunk
            for chunk in self.chunks.values()
            if chunk.artifact_id in artifact_id_set
        ]

    def list_entities(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextEntity]:
        """Return owner-scoped entities."""
        key = (domain_id, owner_type, owner_id)
        return [self.entities[entity_id] for entity_id in self._entity_index[key]]

    def list_relationships(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextRelationship]:
        """Return owner-scoped relationships."""
        key = (domain_id, owner_type, owner_id)
        return [
            self.relationships[relationship_id]
            for relationship_id in self._relationship_index[key]
        ]

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
