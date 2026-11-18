"""SQLAlchemy-backed generic Context Engine repository."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    ReadinessStatus,
    SourceLink,
)
from app.core.context_engine.validation import validate_ingestion_batch
from app.models.context_engine import (
    ContextActionableItemRecord,
    ContextArtifactChunkRecord,
    ContextArtifactRecord,
    ContextEntityRecord,
    ContextIngestionBatchRecord,
    ContextPerspectiveViewRecord,
    ContextRelationshipRecord,
    ContextSignalRecord,
    ContextSourceLinkRecord,
)


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _json_load(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    return json.loads(value)


def _source_links_dump(links: list[SourceLink]) -> str:
    return _json_dump([link.model_dump(mode="json") for link in links])


def _source_links_load(value: str | None) -> list[SourceLink]:
    return [SourceLink(**item) for item in _json_load(value, [])]


class SQLAlchemyContextRepository:
    """Durable repository for generic Context Engine records."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def store_ingestion_batch(self, batch: IngestionBatch) -> IngestionBatch:
        """Persist one validated ingestion batch with a single commit.

        The idempotency record is flushed first so a concurrent request using
        the same owner/domain-scoped key fails on the unique constraint before
        any context rows are written. Any failure rolls back the whole batch.
        """
        validate_ingestion_batch(batch)
        with self.session_factory() as session:
            try:
                if batch.idempotency_key is not None:
                    session.add(self._batch_record(batch))
                    try:
                        session.flush()
                    except IntegrityError as exc:
                        session.rollback()
                        raise IdempotencyKeyExistsError(
                            "An ingestion batch already exists for this "
                            "idempotency key."
                        ) from exc
                for result in batch.results:
                    session.add(self._artifact_record(result.artifact))
                session.flush()
                for result in batch.results:
                    self._add_result_records(session, result)
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError(
                    "Ingestion batch conflicts with existing Context Engine records."
                ) from exc
            except BaseException:
                session.rollback()
                raise
        return batch

    def get_ingestion_batch(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        idempotency_key: str,
    ) -> IngestionBatch | None:
        """Return the stored batch for one owner/domain-scoped idempotency key."""
        with self.session_factory() as session:
            record = session.scalar(
                select(ContextIngestionBatchRecord)
                .where(ContextIngestionBatchRecord.domain_id == domain_id)
                .where(ContextIngestionBatchRecord.owner_type == owner_type.value)
                .where(ContextIngestionBatchRecord.owner_id == owner_id)
                .where(ContextIngestionBatchRecord.idempotency_key == idempotency_key)
            )
            if record is None:
                return None
            return IngestionBatch(
                id=record.id,
                domain_id=record.domain_id,
                owner_type=OwnerType(record.owner_type),
                owner_id=record.owner_id,
                idempotency_key=record.idempotency_key,
                request_fingerprint=record.request_fingerprint,
                results=[
                    IngestionResult.model_validate(item)
                    for item in _json_load(record.results_json, [])
                ],
                created_at=record.created_at,
            )

    def _batch_record(self, batch: IngestionBatch) -> ContextIngestionBatchRecord:
        return ContextIngestionBatchRecord(
            id=batch.id,
            domain_id=batch.domain_id,
            owner_type=batch.owner_type.value,
            owner_id=batch.owner_id,
            idempotency_key=batch.idempotency_key,
            request_fingerprint=batch.request_fingerprint,
            artifact_count=len(batch.results),
            results_json=_json_dump(
                [result.model_dump(mode="json") for result in batch.results]
            ),
            created_at=batch.created_at,
        )

    def _artifact_record(self, artifact: Artifact) -> ContextArtifactRecord:
        return ContextArtifactRecord(
            id=artifact.id,
            domain_id=artifact.domain_id,
            artifact_type_id=artifact.artifact_type_id,
            owner_type=artifact.owner_type.value,
            owner_id=artifact.owner_id,
            title=artifact.title,
            text=artifact.text,
            source_uri=artifact.source_uri,
            metadata_json=_json_dump(artifact.metadata),
            created_at=artifact.created_at,
        )

    def _add_result_records(self, session: Session, result: IngestionResult) -> None:
        """Add chunk, derived-record, and source-link rows for one artifact."""
        artifact = result.artifact
        owner = {
            "domain_id": artifact.domain_id,
            "owner_type": artifact.owner_type.value,
            "owner_id": artifact.owner_id,
        }
        for chunk in result.chunks:
            session.add(
                ContextArtifactChunkRecord(
                    id=chunk.id,
                    artifact_id=chunk.artifact_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    source_link_json=_json_dump(
                        chunk.source_link.model_dump(mode="json")
                    ),
                    metadata_json=_json_dump(chunk.metadata),
                )
            )
            self._add_source_link_record(session, chunk.source_link)
        for entity in result.entities:
            session.add(
                ContextEntityRecord(
                    id=entity.id,
                    **owner,
                    entity_type=entity.entity_type,
                    name=entity.name,
                    source_links_json=_source_links_dump(entity.source_links),
                    metadata_json=_json_dump(entity.metadata),
                )
            )
            self._add_source_link_records(session, entity.source_links)
        for relationship in result.relationships:
            session.add(
                ContextRelationshipRecord(
                    id=relationship.id,
                    **owner,
                    relationship_type=relationship.relationship_type,
                    source_entity_id=relationship.source_entity_id,
                    target_entity_id=relationship.target_entity_id,
                    source_links_json=_source_links_dump(relationship.source_links),
                    metadata_json=_json_dump(relationship.metadata),
                )
            )
            self._add_source_link_records(session, relationship.source_links)
        for signal in result.signals:
            session.add(
                ContextSignalRecord(
                    id=signal.id,
                    **owner,
                    signal_type=signal.signal_type,
                    label=signal.label,
                    value_json=_json_dump(signal.value),
                    source_links_json=_source_links_dump(signal.source_links),
                    metadata_json=_json_dump(signal.metadata),
                )
            )
            self._add_source_link_records(session, signal.source_links)
        for item in result.actionable_items:
            session.add(
                ContextActionableItemRecord(
                    id=item.id,
                    **owner,
                    item_type=item.item_type,
                    title=item.title,
                    description=item.description,
                    readiness_status=item.readiness_status.value,
                    source_links_json=_source_links_dump(item.source_links),
                    metadata_json=_json_dump(item.metadata),
                )
            )
            self._add_source_link_records(session, item.source_links)

    def list_artifacts(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[Artifact]:
        """Return owner-scoped artifacts."""
        with self.session_factory() as session:
            records = session.scalars(
                select(ContextArtifactRecord)
                .where(ContextArtifactRecord.domain_id == domain_id)
                .where(ContextArtifactRecord.owner_type == owner_type.value)
                .where(ContextArtifactRecord.owner_id == owner_id)
                .order_by(ContextArtifactRecord.created_at, ContextArtifactRecord.id)
            ).all()
            return [self._artifact_from_record(record) for record in records]

    def get_artifact(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        artifact_id: str,
    ) -> Artifact | None:
        """Return one owner-scoped artifact, if visible."""
        with self.session_factory() as session:
            record = session.scalar(
                select(ContextArtifactRecord)
                .where(ContextArtifactRecord.id == artifact_id)
                .where(ContextArtifactRecord.domain_id == domain_id)
                .where(ContextArtifactRecord.owner_type == owner_type.value)
                .where(ContextArtifactRecord.owner_id == owner_id)
            )
            return self._artifact_from_record(record) if record is not None else None

    def list_chunks_for_artifact(self, artifact_id: str) -> list[ArtifactChunk]:
        """Return chunks for one artifact."""
        with self.session_factory() as session:
            records = session.scalars(
                select(ContextArtifactChunkRecord)
                .where(ContextArtifactChunkRecord.artifact_id == artifact_id)
                .order_by(ContextArtifactChunkRecord.chunk_index)
            ).all()
            return [self._chunk_from_record(record) for record in records]

    def list_chunks_for_artifacts(self, artifact_ids: list[str]) -> list[ArtifactChunk]:
        """Return chunks for the provided artifact ids."""
        if not artifact_ids:
            return []
        with self.session_factory() as session:
            records = session.scalars(
                select(ContextArtifactChunkRecord)
                .where(ContextArtifactChunkRecord.artifact_id.in_(artifact_ids))
                .order_by(
                    ContextArtifactChunkRecord.artifact_id,
                    ContextArtifactChunkRecord.chunk_index,
                )
            ).all()
            return [self._chunk_from_record(record) for record in records]

    def list_entities(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextEntity]:
        """Return owner-scoped entities."""
        with self.session_factory() as session:
            records = session.scalars(
                select(ContextEntityRecord)
                .where(ContextEntityRecord.domain_id == domain_id)
                .where(ContextEntityRecord.owner_type == owner_type.value)
                .where(ContextEntityRecord.owner_id == owner_id)
                .order_by(ContextEntityRecord.id)
            ).all()
            return [self._entity_from_record(record) for record in records]

    def list_relationships(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextRelationship]:
        """Return owner-scoped relationships."""
        with self.session_factory() as session:
            records = session.scalars(
                select(ContextRelationshipRecord)
                .where(ContextRelationshipRecord.domain_id == domain_id)
                .where(ContextRelationshipRecord.owner_type == owner_type.value)
                .where(ContextRelationshipRecord.owner_id == owner_id)
                .order_by(ContextRelationshipRecord.id)
            ).all()
            return [self._relationship_from_record(record) for record in records]

    def list_signals(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ContextSignal]:
        """Return owner-scoped signals."""
        with self.session_factory() as session:
            records = session.scalars(
                select(ContextSignalRecord)
                .where(ContextSignalRecord.domain_id == domain_id)
                .where(ContextSignalRecord.owner_type == owner_type.value)
                .where(ContextSignalRecord.owner_id == owner_id)
                .order_by(ContextSignalRecord.id)
            ).all()
            return [self._signal_from_record(record) for record in records]

    def list_actionable_items(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> list[ActionableItem]:
        """Return owner-scoped actionable items."""
        with self.session_factory() as session:
            records = session.scalars(
                select(ContextActionableItemRecord)
                .where(ContextActionableItemRecord.domain_id == domain_id)
                .where(ContextActionableItemRecord.owner_type == owner_type.value)
                .where(ContextActionableItemRecord.owner_id == owner_id)
                .order_by(ContextActionableItemRecord.id)
            ).all()
            return [self._item_from_record(record) for record in records]

    def get_perspective_view(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        view_definition_id: str,
    ) -> PerspectiveView | None:
        """Return one cached owner-scoped materialized perspective view."""
        with self.session_factory() as session:
            record = session.scalar(
                select(ContextPerspectiveViewRecord)
                .where(ContextPerspectiveViewRecord.domain_id == domain_id)
                .where(ContextPerspectiveViewRecord.owner_type == owner_type.value)
                .where(ContextPerspectiveViewRecord.owner_id == owner_id)
                .where(
                    ContextPerspectiveViewRecord.view_definition_id
                    == view_definition_id
                )
            )
            return self._view_from_record(record) if record is not None else None

    def store_perspective_view(
        self,
        *,
        view: PerspectiveView,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        source_artifacts: list[Artifact],
    ) -> PerspectiveView:
        """Create or replace one cached owner-scoped perspective view."""
        source_artifact_ids = [artifact.id for artifact in source_artifacts]
        latest_artifact_created_at = max(
            (artifact.created_at for artifact in source_artifacts),
            default=None,
        )
        view_to_store = view.model_copy(deep=True)
        view_to_store.metadata.update(
            {
                "source_artifact_ids": source_artifact_ids,
                "source_artifact_count": len(source_artifact_ids),
                "latest_artifact_created_at": (
                    latest_artifact_created_at.isoformat()
                    if latest_artifact_created_at is not None
                    else None
                ),
                "is_stale": False,
            }
        )
        with self.session_factory() as session:
            record = session.scalar(
                select(ContextPerspectiveViewRecord)
                .where(ContextPerspectiveViewRecord.domain_id == domain_id)
                .where(ContextPerspectiveViewRecord.owner_type == owner_type.value)
                .where(ContextPerspectiveViewRecord.owner_id == owner_id)
                .where(
                    ContextPerspectiveViewRecord.view_definition_id
                    == view.view_definition_id
                )
            )
            if record is None:
                record = ContextPerspectiveViewRecord(
                    id=view_to_store.id,
                    domain_id=domain_id,
                    owner_type=owner_type.value,
                    owner_id=owner_id,
                    view_definition_id=view.view_definition_id,
                    view_json=view_to_store.model_dump_json(),
                    source_artifact_ids_json=_json_dump(source_artifact_ids),
                    artifact_count=len(source_artifact_ids),
                    latest_artifact_created_at=latest_artifact_created_at,
                )
                session.add(record)
            else:
                record.id = view_to_store.id
                record.view_json = view_to_store.model_dump_json()
                record.source_artifact_ids_json = _json_dump(source_artifact_ids)
                record.artifact_count = len(source_artifact_ids)
                record.latest_artifact_created_at = cast(
                    Any, latest_artifact_created_at
                )
            session.commit()
        return view_to_store

    def _add_source_link_records(
        self,
        session: Session,
        links: list[SourceLink],
    ) -> None:
        for link in links:
            self._add_source_link_record(session, link)

    def _add_source_link_record(self, session: Session, link: SourceLink) -> None:
        session.add(
            ContextSourceLinkRecord(
                artifact_id=link.artifact_id,
                chunk_id=link.chunk_id,
                start_offset=link.start_offset,
                end_offset=link.end_offset,
                label=link.label,
                excerpt=link.excerpt,
            )
        )

    def _artifact_from_record(self, record: ContextArtifactRecord) -> Artifact:
        return Artifact(
            id=record.id,
            domain_id=record.domain_id,
            artifact_type_id=record.artifact_type_id,
            owner_type=OwnerType(record.owner_type),
            owner_id=record.owner_id,
            title=record.title,
            text=record.text,
            source_uri=record.source_uri,
            metadata=_json_load(record.metadata_json, {}),
            created_at=record.created_at,
        )

    def _chunk_from_record(self, record: ContextArtifactChunkRecord) -> ArtifactChunk:
        return ArtifactChunk(
            id=record.id,
            artifact_id=record.artifact_id,
            chunk_index=record.chunk_index,
            text=record.text,
            start_offset=record.start_offset,
            end_offset=record.end_offset,
            source_link=SourceLink(**_json_load(record.source_link_json, {})),
            metadata=_json_load(record.metadata_json, {}),
        )

    def _entity_from_record(self, record: ContextEntityRecord) -> ContextEntity:
        return ContextEntity(
            id=record.id,
            entity_type=record.entity_type,
            name=record.name,
            source_links=_source_links_load(record.source_links_json),
            metadata=_json_load(record.metadata_json, {}),
        )

    def _relationship_from_record(
        self, record: ContextRelationshipRecord
    ) -> ContextRelationship:
        return ContextRelationship(
            id=record.id,
            relationship_type=record.relationship_type,
            source_entity_id=record.source_entity_id,
            target_entity_id=record.target_entity_id,
            source_links=_source_links_load(record.source_links_json),
            metadata=_json_load(record.metadata_json, {}),
        )

    def _signal_from_record(self, record: ContextSignalRecord) -> ContextSignal:
        return ContextSignal(
            id=record.id,
            signal_type=record.signal_type,
            label=record.label,
            value=_json_load(record.value_json, None),
            source_links=_source_links_load(record.source_links_json),
            metadata=_json_load(record.metadata_json, {}),
        )

    def _item_from_record(self, record: ContextActionableItemRecord) -> ActionableItem:
        return ActionableItem(
            id=record.id,
            item_type=record.item_type,
            title=record.title,
            description=record.description,
            readiness_status=ReadinessStatus(record.readiness_status),
            source_links=_source_links_load(record.source_links_json),
            metadata=_json_load(record.metadata_json, {}),
        )

    def _view_from_record(
        self, record: ContextPerspectiveViewRecord
    ) -> PerspectiveView:
        view = PerspectiveView.model_validate_json(record.view_json)
        view.metadata.setdefault(
            "source_artifact_ids", _json_load(record.source_artifact_ids_json, [])
        )
        view.metadata.setdefault("source_artifact_count", record.artifact_count)
        view.metadata.setdefault(
            "latest_artifact_created_at",
            (
                record.latest_artifact_created_at.isoformat()
                if record.latest_artifact_created_at is not None
                else None
            ),
        )
        view.metadata.setdefault("generated_at", record.generated_at.isoformat())
        return view
