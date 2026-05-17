"""SQLAlchemy-backed generic Context Engine repository."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ArtifactChunk,
    ContextEntity,
    ContextRelationship,
    ContextSignal,
    OwnerType,
    ReadinessStatus,
    SourceLink,
)
from app.models.context_engine import (
    ContextActionableItemRecord,
    ContextArtifactChunkRecord,
    ContextArtifactRecord,
    ContextEntityRecord,
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


OwnerCache = dict[str, tuple[str, OwnerType, str] | None]


def _owner_from_required_sources(
    session: Session,
    links: list[SourceLink],
    cache: OwnerCache,
    record_type: str,
    record_id: str,
) -> tuple[str, OwnerType, str]:
    if not links:
        raise ValueError(f"{record_type} '{record_id}' must include source links.")
    for link in links:
        if link.artifact_id not in cache:
            artifact = session.get(ContextArtifactRecord, link.artifact_id)
            cache[link.artifact_id] = (
                (
                    artifact.domain_id,
                    OwnerType(artifact.owner_type),
                    artifact.owner_id,
                )
                if artifact is not None
                else None
            )
        owner = cache[link.artifact_id]
        if owner is not None:
            return owner
    raise ValueError(
        f"{record_type} '{record_id}' references unknown source artifact "
        f"'{links[0].artifact_id}'."
    )


class SQLAlchemyContextRepository:
    """Durable repository for generic Context Engine records."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def store_artifact(self, artifact: Artifact) -> Artifact:
        """Persist one artifact."""
        with self.session_factory() as session:
            session.add(
                ContextArtifactRecord(
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
            )
            session.commit()
        return artifact

    def store_chunks(self, chunks: list[ArtifactChunk]) -> list[ArtifactChunk]:
        """Persist artifact chunks."""
        with self.session_factory() as session:
            for chunk in chunks:
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
            session.commit()
        return chunks

    def store_entities(self, entities: list[ContextEntity]) -> list[ContextEntity]:
        """Persist context entities."""
        with self.session_factory() as session:
            owner_cache: OwnerCache = {}
            for entity in entities:
                owner = _owner_from_required_sources(
                    session,
                    entity.source_links,
                    owner_cache,
                    "ContextEntity",
                    entity.id,
                )
                domain_id, owner_type, owner_id = owner
                session.add(
                    ContextEntityRecord(
                        id=entity.id,
                        domain_id=domain_id,
                        owner_type=owner_type.value,
                        owner_id=owner_id,
                        entity_type=entity.entity_type,
                        name=entity.name,
                        source_links_json=_source_links_dump(entity.source_links),
                        metadata_json=_json_dump(entity.metadata),
                    )
                )
                self._add_source_link_records(session, entity.source_links)
            session.commit()
        return entities

    def store_relationships(
        self, relationships: list[ContextRelationship]
    ) -> list[ContextRelationship]:
        """Persist context relationships."""
        with self.session_factory() as session:
            owner_cache: OwnerCache = {}
            for relationship in relationships:
                owner = _owner_from_required_sources(
                    session,
                    relationship.source_links,
                    owner_cache,
                    "ContextRelationship",
                    relationship.id,
                )
                domain_id, owner_type, owner_id = owner
                session.add(
                    ContextRelationshipRecord(
                        id=relationship.id,
                        domain_id=domain_id,
                        owner_type=owner_type.value,
                        owner_id=owner_id,
                        relationship_type=relationship.relationship_type,
                        source_entity_id=relationship.source_entity_id,
                        target_entity_id=relationship.target_entity_id,
                        source_links_json=_source_links_dump(relationship.source_links),
                        metadata_json=_json_dump(relationship.metadata),
                    )
                )
                self._add_source_link_records(session, relationship.source_links)
            session.commit()
        return relationships

    def store_signals(self, signals: list[ContextSignal]) -> list[ContextSignal]:
        """Persist context signals."""
        with self.session_factory() as session:
            owner_cache: OwnerCache = {}
            for signal in signals:
                owner = _owner_from_required_sources(
                    session,
                    signal.source_links,
                    owner_cache,
                    "ContextSignal",
                    signal.id,
                )
                domain_id, owner_type, owner_id = owner
                session.add(
                    ContextSignalRecord(
                        id=signal.id,
                        domain_id=domain_id,
                        owner_type=owner_type.value,
                        owner_id=owner_id,
                        signal_type=signal.signal_type,
                        label=signal.label,
                        value_json=_json_dump(signal.value),
                        source_links_json=_source_links_dump(signal.source_links),
                        metadata_json=_json_dump(signal.metadata),
                    )
                )
                self._add_source_link_records(session, signal.source_links)
            session.commit()
        return signals

    def store_actionable_items(
        self, items: list[ActionableItem]
    ) -> list[ActionableItem]:
        """Persist actionable items."""
        with self.session_factory() as session:
            owner_cache: OwnerCache = {}
            for item in items:
                owner = _owner_from_required_sources(
                    session,
                    item.source_links,
                    owner_cache,
                    "ActionableItem",
                    item.id,
                )
                domain_id, owner_type, owner_id = owner
                session.add(
                    ContextActionableItemRecord(
                        id=item.id,
                        domain_id=domain_id,
                        owner_type=owner_type.value,
                        owner_id=owner_id,
                        item_type=item.item_type,
                        title=item.title,
                        description=item.description,
                        readiness_status=item.readiness_status.value,
                        source_links_json=_source_links_dump(item.source_links),
                        metadata_json=_json_dump(item.metadata),
                    )
                )
                self._add_source_link_records(session, item.source_links)
            session.commit()
        return items

    def index_artifact_outputs(
        self,
        *,
        artifact: Artifact,
        signals: list[ContextSignal],
        actionable_items: list[ActionableItem],
    ) -> None:
        """Durable tables are directly owner-scoped, so no extra index is needed."""
        del artifact, signals, actionable_items

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
