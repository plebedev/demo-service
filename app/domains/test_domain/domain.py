"""Fake Context Engine domain pack for tests and local architecture validation."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.context_engine.interfaces import DomainPack, ViewDefinition
from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ArtifactChunk,
    ArtifactType,
    ContextEntity,
    ContextSignal,
    ExtractionResult,
    PerspectiveView,
    ReadinessStatus,
    SourceLink,
    ViewSection,
)


@dataclass(frozen=True)
class TestDomainExtractor:
    """Extractor that emits generic context from one test artifact."""

    id: str = "test-domain-extractor"

    def extract(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
    ) -> ExtractionResult:
        """Return a small generic extraction result with source links."""
        first_chunk = chunks[0] if chunks else None
        source_link = (
            first_chunk.source_link
            if first_chunk is not None
            else SourceLink(artifact_id=artifact.id, excerpt=artifact.text[:120])
        )
        entity = ContextEntity(
            entity_type="test_entity",
            name=artifact.title or "Untitled artifact",
            source_links=[source_link],
        )
        signal = ContextSignal(
            signal_type="test_signal",
            label="Artifact contains text",
            value=bool(artifact.text.strip()),
            source_links=[source_link],
        )
        item = ActionableItem(
            item_type="test_action",
            title="Review artifact",
            readiness_status=ReadinessStatus.READY,
            source_links=[source_link],
        )
        return ExtractionResult(
            entities=[entity],
            signals=[signal],
            actionable_items=[item],
        )


@dataclass(frozen=True)
class TestPerspectiveBuilder:
    """Perspective builder used to prove domain registration."""

    id: str = "test-perspective-builder"

    def build(self, artifact: Artifact) -> PerspectiveView:
        """Build a simple generic perspective for a test artifact."""
        return PerspectiveView(
            view_definition_id="test-summary",
            title="Test Summary",
            sections=[
                ViewSection(
                    id="summary",
                    title="Summary",
                    content=artifact.text[:200],
                )
            ],
        )


@dataclass(frozen=True)
class TestTaskGenerator:
    """Task generator used to validate registered task extensions."""

    id: str = "test-task-generator"

    def generate(self, artifact: Artifact) -> list[ActionableItem]:
        """Generate one generic test item."""
        return [
            ActionableItem(
                item_type="test_generated_task",
                title=f"Check {artifact.title or 'artifact'}",
                readiness_status=ReadinessStatus.NEEDS_INPUT,
                source_links=[SourceLink(artifact_id=artifact.id)],
            )
        ]


def build_test_domain_pack() -> DomainPack:
    """Build the fake domain pack used by tests."""
    return DomainPack(
        id="test-domain",
        display_name="Test Domain",
        artifact_types=[
            ArtifactType(
                id="note",
                display_name="Note",
                description="Small generic text artifact for validating extensions.",
                accepted_mime_types=["text/plain"],
            )
        ],
        extractors=[TestDomainExtractor()],
        perspective_builders=[TestPerspectiveBuilder()],
        task_generators=[TestTaskGenerator()],
        view_definitions=[
            ViewDefinition(
                id="test-summary",
                display_name="Test Summary",
                description="Minimal registered view for tests.",
            )
        ],
        metadata={"purpose": "architecture-validation"},
    )
