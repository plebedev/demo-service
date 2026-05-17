"""Context Engine orchestration service."""

from __future__ import annotations

from app.core.context_engine.chunking import SimpleTextChunker
from app.core.context_engine.models import (
    Artifact,
    IngestionRequest,
    IngestionResult,
    OwnerType,
    PerspectiveBuildContext,
    PerspectiveView,
)
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.storage import ContextRepository


class ContextEngineService:
    """Coordinate generic artifact ingestion and domain-pack extraction."""

    def __init__(
        self,
        *,
        registry: DomainRegistry,
        repository: ContextRepository,
        default_chunker: SimpleTextChunker | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.default_chunker = default_chunker or SimpleTextChunker()

    def ingest_payload(
        self, domain_id: str, ingestor_id: str, payload: dict[str, object]
    ) -> IngestionResult:
        """Normalize a raw payload with a registered ingestor, then ingest it."""
        domain = self.registry.get_domain(domain_id)
        for ingestor in domain.ingestors:
            if ingestor.id == ingestor_id:
                request = ingestor.ingest(payload)
                if request.domain_id != domain_id:
                    raise ValueError(
                        "Artifact ingestor returned a mismatched domain id."
                    )
                return self.ingest_artifact(request)
        raise ValueError(
            f"Artifact ingestor '{ingestor_id}' is not registered for domain "
            f"'{domain_id}'."
        )

    def ingest_artifact(self, request: IngestionRequest) -> IngestionResult:
        """Ingest one normalized artifact through registered domain extensions.

        Registered ArtifactIngestors normalize external payloads before this method.
        PerspectiveBuilders are intentionally not invoked here; views are materialized
        on demand so ingestion stays focused on durable source facts and signals.
        """
        domain = self.registry.get_domain(request.domain_id)
        valid_artifact_type_ids = {
            artifact_type.id for artifact_type in domain.artifact_types
        }
        if request.artifact_type_id not in valid_artifact_type_ids:
            raise ValueError(
                f"Artifact type '{request.artifact_type_id}' is not registered "
                f"for domain '{request.domain_id}'."
            )
        if not request.text.strip():
            raise ValueError("Artifact text cannot be empty.")

        artifact = self.repository.store_artifact(
            Artifact(
                domain_id=request.domain_id,
                artifact_type_id=request.artifact_type_id,
                owner_type=request.owner_type,
                owner_id=request.owner_id,
                title=request.title,
                text=request.text,
                source_uri=request.source_uri,
                metadata=request.metadata,
            )
        )

        chunker = domain.chunker or self.default_chunker
        chunks = self.repository.store_chunks(chunker.chunk(artifact))

        entities = []
        relationships = []
        signals = []
        actionable_items = []
        extractor_ids = []
        for extractor in domain.extractors:
            result = extractor.extract(artifact, chunks)
            entities.extend(result.entities)
            relationships.extend(result.relationships)
            signals.extend(result.signals)
            actionable_items.extend(result.actionable_items)
            extractor_ids.append(extractor.id)

        for task_generator in domain.task_generators:
            actionable_items.extend(task_generator.generate(artifact))

        entities = self.repository.store_entities(entities)
        relationships = self.repository.store_relationships(relationships)
        signals = self.repository.store_signals(signals)
        actionable_items = self.repository.store_actionable_items(actionable_items)
        self.repository.index_artifact_outputs(
            artifact=artifact,
            signals=signals,
            actionable_items=actionable_items,
        )

        return IngestionResult(
            artifact=artifact,
            chunks=chunks,
            entities=entities,
            relationships=relationships,
            signals=signals,
            actionable_items=actionable_items,
            extractor_ids=extractor_ids,
        )

    def build_perspective(
        self,
        *,
        domain_id: str,
        view_definition_id: str,
        owner_type: OwnerType,
        owner_id: str,
    ) -> PerspectiveView:
        """Build one registered perspective from owner-scoped generic context."""
        domain = self.registry.get_domain(domain_id)
        builder = next(
            (
                candidate
                for candidate in domain.perspective_builders
                if candidate.id == view_definition_id
            ),
            None,
        )
        if builder is None:
            raise ValueError(
                f"Perspective '{view_definition_id}' is not registered for "
                f"domain '{domain_id}'."
            )

        artifacts = self.repository.list_artifacts(
            domain_id=domain_id,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        artifact_ids = [artifact.id for artifact in artifacts]
        context = PerspectiveBuildContext(
            domain_id=domain_id,
            owner_type=owner_type,
            owner_id=owner_id,
            artifacts=artifacts,
            chunks=self.repository.list_chunks_for_artifacts(artifact_ids),
            entities=self.repository.list_entities(
                domain_id=domain_id,
                owner_type=owner_type,
                owner_id=owner_id,
            ),
            relationships=self.repository.list_relationships(
                domain_id=domain_id,
                owner_type=owner_type,
                owner_id=owner_id,
            ),
            signals=self.repository.list_signals(
                domain_id=domain_id,
                owner_type=owner_type,
                owner_id=owner_id,
            ),
            actionable_items=self.repository.list_actionable_items(
                domain_id=domain_id,
                owner_type=owner_type,
                owner_id=owner_id,
            ),
        )
        return builder.build(context)
