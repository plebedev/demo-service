"""Tests for atomic, idempotent Context Engine batch ingestion."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.core.context_engine.errors import (
    ArtifactIngestionError,
    IdempotencyConflictError,
)
from app.core.context_engine.idempotency import (
    normalize_idempotency_key,
    request_fingerprint,
)
from app.core.context_engine.interfaces import DomainPack
from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ArtifactChunk,
    ArtifactType,
    ContextEntity,
    ContextSignal,
    ExtractionResult,
    IngestionIdempotency,
    IngestionRequest,
    IngestionResult,
    OwnerType,
    SourceLink,
)
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.service import ContextEngineService
from app.core.context_engine.sqlalchemy_storage import SQLAlchemyContextRepository
from app.core.context_engine.storage import (
    ContextRepository,
    InMemoryContextRepository,
)
from app.domains.test_domain import build_test_domain_pack

DOMAIN_ID = "batch-domain"


@dataclass
class RecordingExtractor:
    """Extractor whose behavior is driven by markers in artifact text."""

    id: str
    calls: list[str] = field(default_factory=list)
    barrier: threading.Barrier | None = None

    def extract(
        self, artifact: Artifact, chunks: list[ArtifactChunk]
    ) -> ExtractionResult:
        """Return one source-linked entity and signal per artifact."""
        self.calls.append(artifact.text)
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        if "explode-extractor" in artifact.text:
            raise ValueError("Extractor could not read artifact.")
        link = chunks[0].source_link
        if "foreign-source" in artifact.text:
            link = SourceLink(artifact_id="art_foreign")
        signal = ContextSignal(
            signal_type=f"{self.id}_signal",
            label=artifact.text,
            source_links=[link],
        )
        if "fixed-signal-id" in artifact.text and self.id == "first":
            signal.id = "signal_fixed"
        return ExtractionResult(
            entities=[
                ContextEntity(
                    entity_type=f"{self.id}_entity",
                    name=artifact.text,
                    source_links=[link],
                )
            ],
            signals=[signal],
            actionable_items=[
                ActionableItem(
                    item_type=f"{self.id}_item",
                    title=artifact.text,
                    source_links=[link],
                )
            ],
        )


@dataclass
class RecordingTaskGenerator:
    """Task generator that can fail for marked artifacts."""

    id: str = "recording-task-generator"

    def generate(self, artifact: Artifact) -> list[ActionableItem]:
        """Generate one artifact-level actionable item."""
        if "explode-generator" in artifact.text:
            raise ValueError("Task generator failed.")
        return [
            ActionableItem(
                item_type="generated",
                title=artifact.text,
                source_links=[SourceLink(artifact_id=artifact.id)],
            )
        ]


@dataclass
class Harness:
    """Service plus the recording extensions it uses."""

    service: ContextEngineService
    repository: ContextRepository
    first: RecordingExtractor
    second: RecordingExtractor


def build_harness(
    repository: ContextRepository, barrier: threading.Barrier | None = None
) -> Harness:
    """Return a service with a two-extractor batch domain registered."""
    first = RecordingExtractor(id="first", barrier=barrier)
    second = RecordingExtractor(id="second")
    registry = DomainRegistry()
    registry.register_domain(
        DomainPack(
            id=DOMAIN_ID,
            display_name="Batch Domain",
            artifact_types=[ArtifactType(id="note", display_name="Note")],
            extractors=[first, second],
            task_generators=[RecordingTaskGenerator()],
        )
    )
    registry.register_domain(build_test_domain_pack())
    return Harness(
        service=ContextEngineService(registry=registry, repository=repository),
        repository=repository,
        first=first,
        second=second,
    )


def request(text: str, owner_id: str = "owner-1") -> IngestionRequest:
    """Return an ingestion request for the batch domain."""
    return IngestionRequest(
        domain_id=DOMAIN_ID,
        artifact_type_id="note",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id=owner_id,
        text=text,
    )


def idempotency(key: str, payload: object) -> IngestionIdempotency:
    """Return idempotency input for a payload."""
    return IngestionIdempotency(key=key, fingerprint=request_fingerprint(payload))


def stored_artifacts(
    repository: ContextRepository, owner_id: str = "owner-1"
) -> list[Artifact]:
    """Return stored artifacts for the batch domain owner."""
    return repository.list_artifacts(
        domain_id=DOMAIN_ID,
        owner_type=OwnerType.INVITATION_CODE,
        owner_id=owner_id,
    )


def assert_nothing_stored(repository: ContextRepository) -> None:
    """Assert that no batch-domain records are visible."""
    scope = {
        "domain_id": DOMAIN_ID,
        "owner_type": OwnerType.INVITATION_CODE,
        "owner_id": "owner-1",
    }
    assert repository.list_artifacts(**scope) == []
    assert repository.list_entities(**scope) == []
    assert repository.list_signals(**scope) == []
    assert repository.list_actionable_items(**scope) == []


@pytest.fixture(params=["memory", "sqlalchemy"])
def repository(request: pytest.FixtureRequest) -> ContextRepository:
    """Return each repository implementation."""
    if request.param == "memory":
        return InMemoryContextRepository()
    session_factory = request.getfixturevalue("session_factory")
    return SQLAlchemyContextRepository(session_factory)


def test_batch_returns_results_in_request_order_and_preserves_output_order(
    repository: ContextRepository,
) -> None:
    harness = build_harness(repository)

    results = harness.service.ingest_artifacts(
        [request("alpha"), request("beta"), request("gamma")]
    )

    assert [result.artifact.text for result in results] == ["alpha", "beta", "gamma"]
    for result in results:
        assert result.extractor_ids == ["first", "second"]
        assert [entity.entity_type for entity in result.entities] == [
            "first_entity",
            "second_entity",
        ]
        assert [item.item_type for item in result.actionable_items] == [
            "first_item",
            "second_item",
            "generated",
        ]
    assert [artifact.id for artifact in stored_artifacts(repository)] == [
        result.artifact.id for result in results
    ]


@pytest.mark.parametrize(
    ("failing_text", "expected_index", "message"),
    [
        ("explode-extractor", 1, "Extractor could not read artifact."),
        ("explode-generator", 2, "Task generator failed."),
        ("foreign-source", 1, "instead of its source artifact"),
    ],
)
def test_batch_failure_leaves_no_records(
    repository: ContextRepository,
    failing_text: str,
    expected_index: int,
    message: str,
) -> None:
    harness = build_harness(repository)
    texts = ["ok one", "ok two", "ok three"]
    texts[expected_index] = failing_text

    with pytest.raises(ArtifactIngestionError, match=message) as exc_info:
        harness.service.ingest_artifacts(
            [request(text) for text in texts],
            idempotency=idempotency("failure-key", texts),
        )

    assert exc_info.value.index == expected_index
    assert_nothing_stored(repository)
    assert (
        repository.get_ingestion_batch(
            domain_id=DOMAIN_ID,
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="owner-1",
            idempotency_key="failure-key",
        )
        is None
    )


def test_batch_validates_every_request_before_running_extensions(
    repository: ContextRepository,
) -> None:
    harness = build_harness(repository)
    invalid_type = request("valid text").model_copy(
        update={"artifact_type_id": "missing-type"}
    )

    with pytest.raises(ArtifactIngestionError, match="Artifact type") as exc_info:
        harness.service.ingest_artifacts([request("first"), invalid_type])
    with pytest.raises(ArtifactIngestionError, match="cannot be empty"):
        harness.service.ingest_artifacts([request("first"), request("   ")])
    with pytest.raises(ArtifactIngestionError, match="share one domain and owner"):
        harness.service.ingest_artifacts(
            [request("first"), request("second", owner_id="owner-2")]
        )

    assert exc_info.value.index == 1
    assert harness.first.calls == []
    assert_nothing_stored(repository)


def test_batch_persistence_failure_leaves_no_records(
    repository: ContextRepository,
) -> None:
    harness = build_harness(repository)
    harness.service.ingest_artifacts([request("fixed-signal-id original")])

    with pytest.raises(ValueError, match="conflicts with"):
        harness.service.ingest_artifacts(
            [request("new artifact"), request("fixed-signal-id duplicate")],
            idempotency=idempotency("persist-key", "payload"),
        )

    assert [artifact.text for artifact in stored_artifacts(repository)] == [
        "fixed-signal-id original"
    ]
    assert (
        repository.get_ingestion_batch(
            domain_id=DOMAIN_ID,
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="owner-1",
            idempotency_key="persist-key",
        )
        is None
    )


def test_idempotent_replay_returns_stored_results_without_extraction(
    repository: ContextRepository,
) -> None:
    harness = build_harness(repository)
    payload = ["alpha", "beta"]
    requests = [request(text) for text in payload]

    original = harness.service.ingest_artifacts(
        requests, idempotency=idempotency("replay-key", payload)
    )
    replayed = harness.service.ingest_artifacts(
        requests, idempotency=idempotency("replay-key", payload)
    )

    assert replayed == original
    assert harness.first.calls == ["alpha", "beta"]
    assert len(stored_artifacts(repository)) == 2


def test_idempotency_key_reuse_with_different_payload_conflicts(
    repository: ContextRepository,
) -> None:
    harness = build_harness(repository)
    harness.service.ingest_artifact(
        request("alpha"), idempotency=idempotency("conflict-key", "alpha")
    )

    with pytest.raises(IdempotencyConflictError):
        harness.service.ingest_artifact(
            request("beta"), idempotency=idempotency("conflict-key", "beta")
        )

    assert harness.first.calls == ["alpha"]
    assert [artifact.text for artifact in stored_artifacts(repository)] == ["alpha"]


def test_idempotency_keys_are_scoped_to_owner_and_domain(
    repository: ContextRepository,
) -> None:
    harness = build_harness(repository)
    key = idempotency("shared-key", "payload")

    owner_one = harness.service.ingest_artifact(request("one"), idempotency=key)
    owner_two = harness.service.ingest_artifact(
        request("two", owner_id="owner-2"), idempotency=key
    )
    other_domain = harness.service.ingest_artifact(
        IngestionRequest(
            domain_id="test-domain",
            artifact_type_id="note",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="owner-1",
            text="three",
        ),
        idempotency=key,
    )

    assert len({owner_one.artifact.id, owner_two.artifact.id}) == 2
    assert other_domain.artifact.domain_id == "test-domain"
    assert len(stored_artifacts(repository)) == 1
    assert len(stored_artifacts(repository, owner_id="owner-2")) == 1


@pytest.mark.parametrize("same_payload", [True, False])
def test_concurrent_requests_with_same_key_store_one_batch(
    repository: ContextRepository, same_payload: bool
) -> None:
    harness = build_harness(repository, barrier=threading.Barrier(2))
    texts = ["concurrent", "concurrent" if same_payload else "different"]

    def ingest(text: str) -> Callable[[], IngestionResult]:
        return lambda: harness.service.ingest_artifact(
            request(text), idempotency=idempotency("concurrent-key", text)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest(text)) for text in texts]
        outcomes: list[IngestionResult | BaseException] = []
        for future in futures:
            exc = future.exception(timeout=30)
            outcomes.append(exc if exc is not None else future.result())

    assert len(harness.first.calls) == 2
    assert len(stored_artifacts(repository)) == 1
    results = [item for item in outcomes if isinstance(item, IngestionResult)]
    errors = [item for item in outcomes if isinstance(item, BaseException)]
    if same_payload:
        assert errors == []
        assert results[0] == results[1]
    else:
        assert len(results) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], IdempotencyConflictError)


def test_successful_batch_uses_single_commit(engine) -> None:
    counting_factory = sessionmaker(bind=engine, autoflush=False, class_=Session)
    commits: list[object] = []
    event.listen(counting_factory, "after_commit", commits.append)
    harness = build_harness(SQLAlchemyContextRepository(counting_factory))

    harness.service.ingest_artifacts(
        [request(f"artifact {index}") for index in range(20)],
        idempotency=idempotency("commit-key", "payload"),
    )

    assert len(commits) == 1


def test_request_fingerprint_ignores_mapping_order() -> None:
    assert request_fingerprint({"a": 1, "b": [1, 2]}) == request_fingerprint(
        {"b": [1, 2], "a": 1}
    )
    assert request_fingerprint({"a": [1, 2]}) != request_fingerprint({"a": [2, 1]})


@pytest.mark.parametrize("value", ["", "   ", "x" * 256])
def test_normalize_idempotency_key_rejects_unusable_keys(value: str) -> None:
    with pytest.raises(ValueError, match="Idempotency-Key"):
        normalize_idempotency_key(value)


def test_normalize_idempotency_key_trims_whitespace() -> None:
    assert normalize_idempotency_key("  key-1  ") == "key-1"
