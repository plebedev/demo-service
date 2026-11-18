"""Tests for Context Engine ingestion provenance validation."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.core.context_engine.chunking import SimpleTextChunker
from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ContextEntity,
    ContextSignal,
    IngestionBatch,
    IngestionResult,
    OwnerType,
    SourceLink,
)
from app.core.context_engine.storage import InMemoryContextRepository
from app.core.context_engine.validation import (
    validate_ingestion_batch,
    validate_ingestion_result,
)


def make_result(text: str = "Alpha context. Beta context.") -> IngestionResult:
    """Return a valid two-chunk ingestion result."""
    artifact = Artifact(
        domain_id="test-domain",
        artifact_type_id="note",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="owner-1",
        text=text,
    )
    chunks = SimpleTextChunker(chunk_size=16, overlap=2).chunk(artifact)
    second = chunks[1]
    return IngestionResult(
        artifact=artifact,
        chunks=chunks,
        entities=[
            ContextEntity(
                entity_type="thing",
                name="Beta",
                source_links=[
                    SourceLink(
                        artifact_id=artifact.id,
                        chunk_id=second.id,
                        start_offset=second.start_offset,
                        end_offset=second.start_offset + 4,
                    )
                ],
            )
        ],
        relationships=[],
        signals=[
            ContextSignal(
                signal_type="present",
                label="Present",
                source_links=[chunks[0].source_link],
            )
        ],
        actionable_items=[
            ActionableItem(
                item_type="review",
                title="Review",
                source_links=[SourceLink(artifact_id=artifact.id)],
            )
        ],
        extractor_ids=[],
    )


def batch_for(*results: IngestionResult, owner_id: str = "owner-1") -> IngestionBatch:
    """Wrap results in an owner-scoped batch."""
    return IngestionBatch(
        domain_id="test-domain",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id=owner_id,
        results=list(results),
    )


def _foreign_chunk_artifact(result: IngestionResult) -> None:
    result.chunks[0].artifact_id = "art_other"


def _foreign_chunk_source_link(result: IngestionResult) -> None:
    result.chunks[0].source_link.artifact_id = "art_other"


def _chunk_source_link_to_sibling(result: IngestionResult) -> None:
    result.chunks[0].source_link.chunk_id = result.chunks[1].id


def _chunk_offsets_outside_text(result: IngestionResult) -> None:
    result.chunks[-1].end_offset = len(result.artifact.text) + 10


def _duplicate_chunk_index(result: IngestionResult) -> None:
    result.chunks[1].chunk_index = result.chunks[0].chunk_index


def _derived_foreign_artifact(result: IngestionResult) -> None:
    result.signals[0].source_links = [SourceLink(artifact_id="art_other")]


def _derived_unknown_chunk(result: IngestionResult) -> None:
    other = make_result()
    result.entities[0].source_links = [
        SourceLink(artifact_id=result.artifact.id, chunk_id=other.chunks[0].id)
    ]


def _derived_offsets_outside_chunk(result: IngestionResult) -> None:
    link = result.entities[0].source_links[0]
    link.start_offset = 0


def _derived_offsets_inverted(result: IngestionResult) -> None:
    result.actionable_items[0].source_links = [
        SourceLink(artifact_id=result.artifact.id, start_offset=5, end_offset=2)
    ]


def _derived_missing_links(result: IngestionResult) -> None:
    result.actionable_items[0].source_links = []


def _duplicate_derived_id(result: IngestionResult) -> None:
    result.signals.append(result.signals[0].model_copy())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_foreign_chunk_artifact, "instead of its source artifact"),
        (_foreign_chunk_source_link, "instead of its source artifact"),
        (_chunk_source_link_to_sibling, "source link references chunk"),
        (_chunk_offsets_outside_text, "offsets fall outside artifact"),
        (_duplicate_chunk_index, "duplicate chunk index"),
        (_derived_foreign_artifact, "instead of its source artifact"),
        (_derived_unknown_chunk, "does not belong to artifact"),
        (_derived_offsets_outside_chunk, "offsets fall outside"),
        (_derived_offsets_inverted, "start offset exceeds"),
        (_derived_missing_links, "must include source links"),
        (_duplicate_derived_id, "is duplicated"),
    ],
)
def test_validation_rejects_mismatched_provenance(
    mutate: Callable[[IngestionResult], None], message: str
) -> None:
    result = make_result()
    validate_ingestion_result(result)
    mutate(result)

    with pytest.raises(ValueError, match=message):
        validate_ingestion_result(result)


def test_validation_rejects_batch_scope_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match the ingestion batch"):
        validate_ingestion_batch(batch_for(make_result(), owner_id="owner-2"))


def test_validation_rejects_derived_links_to_sibling_artifacts() -> None:
    first = make_result()
    second = make_result()
    second.signals[0].source_links = [first.chunks[0].source_link]

    with pytest.raises(ValueError, match="instead of its source artifact"):
        validate_ingestion_batch(batch_for(first, second))


def test_validation_rejects_duplicate_ids_across_batch() -> None:
    first = make_result()
    second = make_result()
    second.signals[0].id = first.signals[0].id

    with pytest.raises(ValueError, match="is duplicated"):
        validate_ingestion_batch(batch_for(first, second))


def test_validation_requires_key_and_fingerprint_together() -> None:
    batch = batch_for(make_result())
    batch.idempotency_key = "key-without-fingerprint"

    with pytest.raises(ValueError, match="provided together"):
        validate_ingestion_batch(batch)


def test_in_memory_repository_validates_before_storing() -> None:
    repository = InMemoryContextRepository()
    valid = make_result()
    invalid = make_result()
    _derived_foreign_artifact(invalid)

    with pytest.raises(ValueError, match="instead of its source artifact"):
        repository.store_ingestion_batch(batch_for(valid, invalid))

    assert repository.artifacts == {}
    assert repository.chunks == {}
    assert repository.signals == {}
