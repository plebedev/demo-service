"""Storage abstractions and in-memory adapter for Context Engine records."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Protocol

from app.core.context_engine.errors import IdempotencyKeyExistsError
from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ArtifactChunk,
    ContextEntity,
    ContextRelationship,
    ContextSignal,
    IngestionBatch,
    IngestionResult,
    OwnerType,
    PerspectiveView,
)
from app.core.context_engine.validation import validate_ingestion_batch


class ContextRepository(Protocol):
    """Repository contract for Context Engine persistence."""

    def store_ingestion_batch(self, batch: IngestionBatch) -> IngestionBatch:
        """Atomically persist every record produced by one ingestion batch.

        Implementations validate provenance before writing, persist artifacts,
        chunks, derived records, source links, and the idempotency record (when
        a key is present) all-or-nothing, and raise
        ``IdempotencyKeyExistsError`` when the owner/domain-scoped key already
        has a stored batch.
        """
        ...

    def get_ingestion_batch(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        idempotency_key: str,
    ) -> IngestionBatch | None:
        """Return the stored batch for one owner/domain-scoped idempotency key."""
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

    def get_artifact(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        artifact_id: str,
    ) -> Artifact | None:
        """Return one owner-scoped artifact, if visible."""
        ...

    def list_chunks_for_artifact(self, artifact_id: str) -> list[ArtifactChunk]:
        """Return chunks for one artifact."""
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

    def get_perspective_view(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        view_definition_id: str,
    ) -> PerspectiveView | None:
        """Return one cached materialized perspective view, if available."""
        ...

    def store_perspective_view(
        self,
        *,
        view: PerspectiveView,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        source_artifacts: list[Artifact],
    ) -> PerspectiveView:
        """Persist one materialized perspective view."""
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
        self.perspective_views: dict[
            tuple[str, OwnerType, str, str], PerspectiveView
        ] = {}
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
        self.ingestion_batches: dict[
            tuple[str, OwnerType, str, str], IngestionBatch
        ] = {}
        self._lock = threading.RLock()

    def store_ingestion_batch(self, batch: IngestionBatch) -> IngestionBatch:
        """Validate and store one ingestion batch all-or-nothing."""
        validate_ingestion_batch(batch)
        stored = batch.model_copy(deep=True)
        with self._lock:
            key = self._batch_key(stored)
            if key is not None and key in self.ingestion_batches:
                raise IdempotencyKeyExistsError(
                    "An ingestion batch already exists for this idempotency key."
                )
            self._ensure_new_record_ids(stored)
            for result in stored.results:
                self._apply_result(result)
            if key is not None:
                self.ingestion_batches[key] = stored
        return stored.model_copy(deep=True)

    def get_ingestion_batch(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        idempotency_key: str,
    ) -> IngestionBatch | None:
        """Return the stored batch for one owner/domain-scoped idempotency key."""
        with self._lock:
            batch = self.ingestion_batches.get(
                (domain_id, owner_type, owner_id, idempotency_key)
            )
            return batch.model_copy(deep=True) if batch is not None else None

    @staticmethod
    def _batch_key(batch: IngestionBatch) -> tuple[str, OwnerType, str, str] | None:
        if batch.idempotency_key is None:
            return None
        return (
            batch.domain_id,
            batch.owner_type,
            batch.owner_id,
            batch.idempotency_key,
        )

    def _ensure_new_record_ids(self, batch: IngestionBatch) -> None:
        """Reject batches that would overwrite already-stored records."""
        stores: list[tuple[str, dict[str, Any], list[str]]] = [
            (
                "Artifact",
                self.artifacts,
                [result.artifact.id for result in batch.results],
            ),
            (
                "ArtifactChunk",
                self.chunks,
                [chunk.id for result in batch.results for chunk in result.chunks],
            ),
            (
                "ContextEntity",
                self.entities,
                [entity.id for result in batch.results for entity in result.entities],
            ),
            (
                "ContextRelationship",
                self.relationships,
                [rel.id for result in batch.results for rel in result.relationships],
            ),
            (
                "ContextSignal",
                self.signals,
                [signal.id for result in batch.results for signal in result.signals],
            ),
            (
                "ActionableItem",
                self.actionable_items,
                [
                    item.id
                    for result in batch.results
                    for item in result.actionable_items
                ],
            ),
        ]
        for record_type, existing, record_ids in stores:
            for record_id in record_ids:
                if record_id in existing:
                    raise ValueError(
                        f"{record_type} id '{record_id}' conflicts with an existing "
                        "Context Engine record."
                    )

    def _apply_result(self, result: IngestionResult) -> None:
        """Store and index one validated ingestion result."""
        artifact = result.artifact
        key = (artifact.domain_id, artifact.owner_type, artifact.owner_id)
        self.artifacts[artifact.id] = artifact
        self._artifact_index[key].append(artifact.id)
        for chunk in result.chunks:
            self.chunks[chunk.id] = chunk
        for entity in result.entities:
            self.entities[entity.id] = entity
            self._entity_index[key].append(entity.id)
        for relationship in result.relationships:
            self.relationships[relationship.id] = relationship
            self._relationship_index[key].append(relationship.id)
        for signal in result.signals:
            self.signals[signal.id] = signal
            self._signal_index[key].append(signal.id)
        for item in result.actionable_items:
            self.actionable_items[item.id] = item
            self._task_index[key].append(item.id)

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

    def get_artifact(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        artifact_id: str,
    ) -> Artifact | None:
        """Return one owner-scoped artifact, if visible."""
        artifact = self.artifacts.get(artifact_id)
        if (
            artifact is None
            or artifact.domain_id != domain_id
            or artifact.owner_type != owner_type
            or artifact.owner_id != owner_id
        ):
            return None
        return artifact

    def list_chunks_for_artifact(self, artifact_id: str) -> list[ArtifactChunk]:
        """Return chunks for one artifact."""
        return [
            chunk for chunk in self.chunks.values() if chunk.artifact_id == artifact_id
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

    def get_perspective_view(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        view_definition_id: str,
    ) -> PerspectiveView | None:
        """Return one cached owner-scoped perspective view."""
        key = (domain_id, owner_type, owner_id, view_definition_id)
        view = self.perspective_views.get(key)
        return view.model_copy(deep=True) if view is not None else None

    def store_perspective_view(
        self,
        *,
        view: PerspectiveView,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        source_artifacts: list[Artifact],
    ) -> PerspectiveView:
        """Store one owner-scoped perspective view in memory."""
        key = (domain_id, owner_type, owner_id, view.view_definition_id)
        stored = view.model_copy(deep=True)
        stored.metadata.update(_perspective_cache_metadata(source_artifacts))
        self.perspective_views[key] = stored
        return stored.model_copy(deep=True)


def _perspective_cache_metadata(source_artifacts: list[Artifact]) -> dict[str, object]:
    """Return generic cache metadata for source artifacts."""
    latest = max((artifact.created_at for artifact in source_artifacts), default=None)
    return {
        "source_artifact_ids": [artifact.id for artifact in source_artifacts],
        "source_artifact_count": len(source_artifacts),
        "latest_artifact_created_at": latest.isoformat() if latest else None,
        "is_stale": False,
    }
