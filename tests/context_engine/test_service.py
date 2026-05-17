"""Tests for Context Engine ingestion orchestration."""

from __future__ import annotations

import pytest

from app.core.context_engine.models import IngestionRequest, OwnerType
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.service import ContextEngineService
from app.core.context_engine.storage import InMemoryContextRepository
from app.domains.test_domain import build_test_domain_pack


def build_service() -> ContextEngineService:
    """Return a Context Engine service with the fake domain registered."""
    registry = DomainRegistry()
    registry.register_domain(build_test_domain_pack())
    return ContextEngineService(
        registry=registry,
        repository=InMemoryContextRepository(),
    )


def test_artifact_ingestion_chunks_extracts_tasks_and_preserves_source_links() -> None:
    service = build_service()

    result = service.ingest_artifact(
        IngestionRequest(
            domain_id="test-domain",
            artifact_type_id="note",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="42",
            title="Source note",
            text="Alpha context.\nBeta context.",
            source_uri="memory://source-note",
        )
    )

    assert result.artifact.domain_id == "test-domain"
    assert result.artifact.owner_type == OwnerType.INVITATION_CODE
    assert result.artifact.owner_id == "42"
    assert result.chunks
    assert result.extractor_ids == ["test-domain-extractor"]
    assert [entity.entity_type for entity in result.entities] == ["test_entity"]
    assert [signal.signal_type for signal in result.signals] == ["test_signal"]
    assert {item.item_type for item in result.actionable_items} == {
        "test_action",
        "test_generated_task",
    }
    assert result.chunks[0].source_link.artifact_id == result.artifact.id
    assert result.signals[0].source_links[0].artifact_id == result.artifact.id
    assert result.signals[0].source_links[0].chunk_id == result.chunks[0].id


def test_ingestion_rejects_invalid_domain() -> None:
    service = build_service()

    with pytest.raises(KeyError, match="not registered"):
        service.ingest_artifact(
            IngestionRequest(
                domain_id="missing-domain",
                artifact_type_id="note",
                owner_type=OwnerType.INVITATION_CODE,
                owner_id="42",
                text="content",
            )
        )


def test_ingestion_rejects_invalid_artifact_type() -> None:
    service = build_service()

    with pytest.raises(ValueError, match="Artifact type"):
        service.ingest_artifact(
            IngestionRequest(
                domain_id="test-domain",
                artifact_type_id="missing-type",
                owner_type=OwnerType.INVITATION_CODE,
                owner_id="42",
                text="content",
            )
        )


def test_fake_domain_perspective_builder_and_task_generator_work() -> None:
    registry = DomainRegistry()
    pack = build_test_domain_pack()
    registry.register_domain(pack)
    service = ContextEngineService(
        registry=registry,
        repository=InMemoryContextRepository(),
    )

    result = service.ingest_artifact(
        IngestionRequest(
            domain_id="test-domain",
            artifact_type_id="note",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="42",
            title="Perspective source",
            text="Perspective content",
        )
    )
    view = pack.perspective_builders[0].build(result.artifact)

    assert view.view_definition_id == "test-summary"
    assert view.sections[0].content == "Perspective content"
    assert result.actionable_items[-1].item_type == "test_generated_task"
