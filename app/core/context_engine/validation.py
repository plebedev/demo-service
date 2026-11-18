"""Provenance and scope validation for Context Engine ingestion output."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from app.core.context_engine.models import (
    Artifact,
    ArtifactChunk,
    IngestionBatch,
    IngestionResult,
    SourceLink,
)


def validate_ingestion_result(result: IngestionResult) -> None:
    """Validate that chunks and derived records belong to their source artifact.

    Every chunk must belong to the artifact that produced it, and every derived
    record must carry at least one source link pointing at that artifact and,
    when a chunk is referenced, at one of that artifact's chunks. Offsets must
    stay inside the referenced chunk or artifact text.
    """
    artifact = result.artifact
    chunks_by_id = _validate_chunks(artifact, result.chunks)
    derived: list[tuple[str, Sequence[_Derived]]] = [
        ("ContextEntity", result.entities),
        ("ContextRelationship", result.relationships),
        ("ContextSignal", result.signals),
        ("ActionableItem", result.actionable_items),
    ]
    for record_type, records in derived:
        _require_unique(record_type, (record.id for record in records))
        for record in records:
            if not record.source_links:
                raise ValueError(
                    f"{record_type} '{record.id}' must include source links."
                )
            for link in record.source_links:
                _validate_source_link(
                    link,
                    artifact=artifact,
                    chunks_by_id=chunks_by_id,
                    record_type=record_type,
                    record_id=record.id,
                )


def validate_ingestion_batch(batch: IngestionBatch) -> None:
    """Validate scope, provenance, and identifier uniqueness for one batch."""
    if (batch.idempotency_key is None) != (batch.request_fingerprint is None):
        raise ValueError(
            "Ingestion batch idempotency key and request fingerprint must be "
            "provided together."
        )
    if not batch.results:
        raise ValueError("Ingestion batch must include at least one artifact.")
    for result in batch.results:
        artifact = result.artifact
        if (
            artifact.domain_id != batch.domain_id
            or artifact.owner_type != batch.owner_type
            or artifact.owner_id != batch.owner_id
        ):
            raise ValueError(
                f"Artifact '{artifact.id}' does not match the ingestion batch "
                "domain and owner."
            )
        validate_ingestion_result(result)
    _require_unique("Artifact", (result.artifact.id for result in batch.results))
    _require_unique(
        "ArtifactChunk",
        (chunk.id for result in batch.results for chunk in result.chunks),
    )
    _require_unique(
        "ContextEntity",
        (entity.id for result in batch.results for entity in result.entities),
    )
    _require_unique(
        "ContextRelationship",
        (rel.id for result in batch.results for rel in result.relationships),
    )
    _require_unique(
        "ContextSignal",
        (signal.id for result in batch.results for signal in result.signals),
    )
    _require_unique(
        "ActionableItem",
        (item.id for result in batch.results for item in result.actionable_items),
    )


class _Derived(Protocol):
    """Structural type for derived records carrying source links."""

    @property
    def id(self) -> str:
        """Record id."""
        ...

    @property
    def source_links(self) -> list[SourceLink]:
        """Record source links."""
        ...


def _validate_chunks(
    artifact: Artifact, chunks: list[ArtifactChunk]
) -> dict[str, ArtifactChunk]:
    """Validate artifact chunks and return them by id."""
    _require_unique("ArtifactChunk", (chunk.id for chunk in chunks))
    seen_indexes: set[int] = set()
    text_length = len(artifact.text)
    chunks_by_id: dict[str, ArtifactChunk] = {}
    for chunk in chunks:
        if chunk.artifact_id != artifact.id:
            raise ValueError(
                f"ArtifactChunk '{chunk.id}' references artifact "
                f"'{chunk.artifact_id}' instead of its source artifact "
                f"'{artifact.id}'."
            )
        if chunk.chunk_index in seen_indexes:
            raise ValueError(
                f"Artifact '{artifact.id}' has duplicate chunk index "
                f"{chunk.chunk_index}."
            )
        seen_indexes.add(chunk.chunk_index)
        if chunk.start_offset > chunk.end_offset or chunk.end_offset > text_length:
            raise ValueError(
                f"ArtifactChunk '{chunk.id}' offsets fall outside artifact "
                f"'{artifact.id}'."
            )
        chunks_by_id[chunk.id] = chunk
    for chunk in chunks:
        link = chunk.source_link
        if link.chunk_id is not None and link.chunk_id != chunk.id:
            raise ValueError(
                f"ArtifactChunk '{chunk.id}' source link references chunk "
                f"'{link.chunk_id}'."
            )
        _validate_source_link(
            link,
            artifact=artifact,
            chunks_by_id={chunk.id: chunk},
            record_type="ArtifactChunk",
            record_id=chunk.id,
            bounds=(chunk.start_offset, chunk.end_offset),
        )
    return chunks_by_id


def _validate_source_link(
    link: SourceLink,
    *,
    artifact: Artifact,
    chunks_by_id: dict[str, ArtifactChunk],
    record_type: str,
    record_id: str,
    bounds: tuple[int, int] | None = None,
) -> None:
    """Validate one source link against its producing artifact."""
    if link.artifact_id != artifact.id:
        raise ValueError(
            f"{record_type} '{record_id}' references artifact "
            f"'{link.artifact_id}' instead of its source artifact '{artifact.id}'."
        )
    if bounds is None:
        bounds = (0, len(artifact.text))
    if link.chunk_id is not None:
        chunk = chunks_by_id.get(link.chunk_id)
        if chunk is None:
            raise ValueError(
                f"{record_type} '{record_id}' references chunk '{link.chunk_id}' "
                f"that does not belong to artifact '{artifact.id}'."
            )
        bounds = (chunk.start_offset, chunk.end_offset)
    lower, upper = bounds
    for offset in (link.start_offset, link.end_offset):
        if offset is not None and not lower <= offset <= upper:
            raise ValueError(
                f"{record_type} '{record_id}' source link offsets fall outside "
                "the referenced source text."
            )
    if (
        link.start_offset is not None
        and link.end_offset is not None
        and link.start_offset > link.end_offset
    ):
        raise ValueError(
            f"{record_type} '{record_id}' source link start offset exceeds its "
            "end offset."
        )


def _require_unique(record_type: str, ids: Iterable[str]) -> None:
    """Raise when one record id appears more than once."""
    seen: set[str] = set()
    for record_id in ids:
        if record_id in seen:
            raise ValueError(f"{record_type} id '{record_id}' is duplicated.")
        seen.add(record_id)
