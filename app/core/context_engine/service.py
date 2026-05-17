"""Context Engine orchestration service."""

from __future__ import annotations

from app.core.context_engine.chunking import SimpleTextChunker
from app.core.context_engine.models import Artifact, IngestionRequest, IngestionResult
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

    def ingest_artifact(self, request: IngestionRequest) -> IngestionResult:
        """Ingest one artifact through registered domain extensions."""
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

        index_outputs = getattr(self.repository, "index_artifact_outputs", None)
        if callable(index_outputs):
            index_outputs(
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
