"""Tests for SQLAlchemy Context Engine persistence behavior."""

from __future__ import annotations

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.context_engine.chunking import SimpleTextChunker
from app.core.context_engine.errors import IdempotencyKeyExistsError
from app.core.context_engine.models import (
    Artifact,
    ContextSignal,
    IngestionBatch,
    IngestionResult,
    OwnerType,
    PerspectiveView,
    SourceLink,
    ViewSection,
)
from app.core.context_engine.sqlalchemy_storage import SQLAlchemyContextRepository
from app.models.context_engine import (
    ContextArtifactChunkRecord,
    ContextArtifactRecord,
    ContextIngestionBatchRecord,
    ContextSignalRecord,
    ContextSourceLinkRecord,
)


def make_result(
    *,
    owner_id: str = "owner-1",
    text: str = "Grounded source",
    signal_id: str | None = None,
) -> IngestionResult:
    """Return a valid source-grounded ingestion result for one artifact."""
    artifact = Artifact(
        domain_id="test-domain",
        artifact_type_id="note",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id=owner_id,
        text=text,
    )
    chunks = SimpleTextChunker().chunk(artifact)
    signal = ContextSignal(
        signal_type="grounded",
        label="Grounded",
        value=True,
        source_links=[chunks[0].source_link],
    )
    if signal_id is not None:
        signal.id = signal_id
    return IngestionResult(
        artifact=artifact,
        chunks=chunks,
        entities=[],
        relationships=[],
        signals=[signal],
        actionable_items=[],
        extractor_ids=["test-extractor"],
    )


def make_batch(
    *results: IngestionResult,
    owner_id: str = "owner-1",
    key: str | None = None,
    fingerprint: str | None = None,
) -> IngestionBatch:
    """Wrap ingestion results in an owner-scoped batch."""
    return IngestionBatch(
        domain_id="test-domain",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id=owner_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        results=list(results),
    )


def count_rows(session_factory: sessionmaker[Session], model: type) -> int:
    """Return the row count for one ORM model."""
    with session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_sqlalchemy_repository_rejects_source_link_less_signals(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    result = make_result()
    result.signals[0].source_links = []

    with pytest.raises(ValueError, match="must include source links"):
        repository.store_ingestion_batch(make_batch(result))

    assert count_rows(session_factory, ContextArtifactRecord) == 0


def test_sqlalchemy_repository_rejects_foreign_source_artifacts(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    existing = make_result(owner_id="other-owner")
    repository.store_ingestion_batch(make_batch(existing, owner_id="other-owner"))
    result = make_result()
    result.signals[0].source_links = [
        SourceLink(artifact_id=existing.artifact.id),
    ]

    with pytest.raises(ValueError, match="instead of its source artifact"):
        repository.store_ingestion_batch(make_batch(result))

    assert count_rows(session_factory, ContextArtifactRecord) == 1
    assert (
        repository.list_signals(
            domain_id="test-domain",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="owner-1",
        )
        == []
    )


def test_sqlalchemy_repository_persists_batch_with_one_commit(engine) -> None:
    counting_factory = sessionmaker(bind=engine, autoflush=False, class_=Session)
    commits: list[object] = []
    event.listen(counting_factory, "after_commit", commits.append)
    repository = SQLAlchemyContextRepository(counting_factory)
    results = [make_result(text=f"Grounded source {index}") for index in range(5)]

    stored = repository.store_ingestion_batch(
        make_batch(*results, key="batch-key", fingerprint="fingerprint")
    )

    assert len(commits) == 1
    assert [result.artifact.id for result in stored.results] == [
        result.artifact.id for result in results
    ]
    assert count_rows(counting_factory, ContextArtifactRecord) == 5
    assert count_rows(counting_factory, ContextArtifactChunkRecord) == 5
    assert count_rows(counting_factory, ContextSignalRecord) == 5
    assert count_rows(counting_factory, ContextSourceLinkRecord) == 10
    assert count_rows(counting_factory, ContextIngestionBatchRecord) == 1


def test_sqlalchemy_repository_rolls_back_whole_batch_on_conflict(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    repository.store_ingestion_batch(make_batch(make_result(signal_id="signal_fixed")))

    with pytest.raises(ValueError, match="conflicts with existing"):
        repository.store_ingestion_batch(
            make_batch(
                make_result(text="New source"),
                make_result(text="Colliding source", signal_id="signal_fixed"),
                key="rollback-key",
                fingerprint="fingerprint",
            )
        )

    assert count_rows(session_factory, ContextArtifactRecord) == 1
    assert count_rows(session_factory, ContextArtifactChunkRecord) == 1
    assert count_rows(session_factory, ContextSignalRecord) == 1
    assert count_rows(session_factory, ContextSourceLinkRecord) == 2
    assert count_rows(session_factory, ContextIngestionBatchRecord) == 0


def test_sqlalchemy_repository_round_trips_idempotent_batches(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    first = make_result(text="First source")
    second = make_result(text="Second source")
    repository.store_ingestion_batch(
        make_batch(first, second, key="replay-key", fingerprint="fingerprint")
    )

    loaded = repository.get_ingestion_batch(
        domain_id="test-domain",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="owner-1",
        idempotency_key="replay-key",
    )

    assert loaded is not None
    assert loaded.request_fingerprint == "fingerprint"
    assert loaded.results == [first, second]
    assert (
        repository.get_ingestion_batch(
            domain_id="test-domain",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="other-owner",
            idempotency_key="replay-key",
        )
        is None
    )


def test_sqlalchemy_repository_rejects_duplicate_idempotency_keys(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    repository.store_ingestion_batch(
        make_batch(make_result(), key="dup-key", fingerprint="fingerprint")
    )

    with pytest.raises(IdempotencyKeyExistsError):
        repository.store_ingestion_batch(
            make_batch(
                make_result(text="Duplicate source"),
                key="dup-key",
                fingerprint="fingerprint",
            )
        )
    repository.store_ingestion_batch(
        make_batch(
            make_result(owner_id="owner-2"),
            owner_id="owner-2",
            key="dup-key",
            fingerprint="fingerprint",
        )
    )

    assert count_rows(session_factory, ContextArtifactRecord) == 2
    assert count_rows(session_factory, ContextIngestionBatchRecord) == 2


def test_sqlalchemy_repository_persists_source_grounded_signals(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    result = make_result()

    repository.store_ingestion_batch(make_batch(result))

    signals = repository.list_signals(
        domain_id="test-domain",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="owner-1",
    )
    assert [signal.id for signal in signals] == [result.signals[0].id]
    assert signals[0].source_links[0].artifact_id == result.artifact.id
    assert repository.list_chunks_for_artifact(result.artifact.id) == result.chunks


def test_sqlalchemy_repository_persists_perspective_views(session_factory) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    artifact = make_result(text="Perspective source").artifact
    view = PerspectiveView(
        view_definition_id="test-summary",
        title="Test Summary",
        sections=[ViewSection(id="summary", title="Summary", content="Cached")],
    )

    stored = repository.store_perspective_view(
        view=view,
        domain_id="test-domain",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="owner-1",
        source_artifacts=[artifact],
    )
    loaded = repository.get_perspective_view(
        domain_id="test-domain",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="owner-1",
        view_definition_id="test-summary",
    )

    assert loaded is not None
    assert loaded.id == stored.id
    assert loaded.sections[0].content == "Cached"
    assert loaded.metadata["source_artifact_ids"] == [artifact.id]
    assert loaded.metadata["source_artifact_count"] == 1
