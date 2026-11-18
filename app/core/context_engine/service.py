"""Context Engine orchestration service."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Callable, cast

from app.core.context_engine.chunking import SimpleTextChunker
from app.core.context_engine.errors import (
    ArtifactIngestionError,
    IdempotencyConflictError,
    IdempotencyKeyExistsError,
)
from app.core.context_engine.interfaces import DomainPack
from app.core.context_engine.llm import ContextExecutionContext
from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ExtractionResult,
    IngestionBatch,
    IngestionIdempotency,
    IngestionRequest,
    IngestionResult,
    OwnerType,
    PerspectiveBuildContext,
    PerspectiveView,
)
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.storage import ContextRepository
from app.core.context_engine.validation import validate_ingestion_result


class ContextEngineService:
    """Coordinate generic artifact ingestion and domain-pack extraction."""

    def __init__(
        self,
        *,
        registry: DomainRegistry,
        repository: ContextRepository,
        default_chunker: SimpleTextChunker | None = None,
        execution_context: ContextExecutionContext | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.default_chunker = default_chunker or SimpleTextChunker()
        self.execution_context = execution_context

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

    def ingest_artifact(
        self,
        request: IngestionRequest,
        *,
        idempotency: IngestionIdempotency | None = None,
    ) -> IngestionResult:
        """Ingest one normalized artifact as a single-item atomic batch."""
        return self.ingest_artifacts([request], idempotency=idempotency)[0]

    def ingest_artifacts(
        self,
        requests: Sequence[IngestionRequest],
        *,
        idempotency: IngestionIdempotency | None = None,
    ) -> list[IngestionResult]:
        """Ingest normalized artifacts atomically through domain extensions.

        Every request must share one domain and owner. All requests are
        validated before any extension runs, then each artifact is chunked,
        extracted, and passed through task generators in request order. Outputs
        are persisted by one repository call, so a failure for any artifact
        leaves no records behind. Results are returned in request order.

        When ``idempotency`` is provided, a previously stored batch for the same
        owner/domain-scoped key is returned without rerunning extraction, and a
        stored batch with a different fingerprint raises
        ``IdempotencyConflictError``.

        Registered ArtifactIngestors normalize external payloads before this method.
        PerspectiveBuilders are intentionally not invoked here; views are materialized
        on demand so ingestion stays focused on durable source facts and signals.
        """
        if not requests:
            raise ValueError("At least one artifact is required for ingestion.")
        first = requests[0]
        domain = self.registry.get_domain(first.domain_id)
        for index, request in enumerate(requests):
            if (
                request.domain_id != first.domain_id
                or request.owner_type != first.owner_type
                or request.owner_id != first.owner_id
            ):
                raise ArtifactIngestionError(
                    index,
                    "All artifacts in an ingestion batch must share one domain "
                    "and owner.",
                )

        if idempotency is not None:
            replayed = self.replay_idempotent_ingestion(
                domain_id=first.domain_id,
                owner_type=first.owner_type,
                owner_id=first.owner_id,
                idempotency=idempotency,
            )
            if replayed is not None:
                return replayed

        for index, request in enumerate(requests):
            try:
                self._validate_request(domain, request)
            except ValueError as exc:
                raise ArtifactIngestionError(index, str(exc)) from exc

        results: list[IngestionResult] = []
        for index, request in enumerate(requests):
            try:
                result = self._run_extensions(domain, request)
                validate_ingestion_result(result)
            except ArtifactIngestionError:
                raise
            except ValueError as exc:
                raise ArtifactIngestionError(index, str(exc)) from exc
            results.append(result)

        batch = IngestionBatch(
            domain_id=first.domain_id,
            owner_type=first.owner_type,
            owner_id=first.owner_id,
            idempotency_key=idempotency.key if idempotency else None,
            request_fingerprint=idempotency.fingerprint if idempotency else None,
            results=results,
        )
        try:
            stored = self.repository.store_ingestion_batch(batch)
        except IdempotencyKeyExistsError:
            if idempotency is None:
                raise
            replayed = self.replay_idempotent_ingestion(
                domain_id=first.domain_id,
                owner_type=first.owner_type,
                owner_id=first.owner_id,
                idempotency=idempotency,
            )
            if replayed is None:
                raise
            return replayed
        return stored.results

    def replay_idempotent_ingestion(
        self,
        *,
        domain_id: str,
        owner_type: OwnerType,
        owner_id: str,
        idempotency: IngestionIdempotency,
    ) -> list[IngestionResult] | None:
        """Return stored results for an idempotency key, if one was recorded.

        Raises ``IdempotencyConflictError`` when the key was recorded for a
        request with a different fingerprint.
        """
        batch = self.repository.get_ingestion_batch(
            domain_id=domain_id,
            owner_type=owner_type,
            owner_id=owner_id,
            idempotency_key=idempotency.key,
        )
        if batch is None:
            return None
        if batch.request_fingerprint != idempotency.fingerprint:
            raise IdempotencyConflictError(
                "Idempotency-Key was already used with a different request payload."
            )
        return batch.results

    @staticmethod
    def _validate_request(domain: DomainPack, request: IngestionRequest) -> None:
        """Validate one request against its registered domain pack."""
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

    def _run_extensions(
        self, domain: DomainPack, request: IngestionRequest
    ) -> IngestionResult:
        """Chunk, extract, and generate tasks for one artifact without storing."""
        artifact = Artifact(
            domain_id=request.domain_id,
            artifact_type_id=request.artifact_type_id,
            owner_type=request.owner_type,
            owner_id=request.owner_id,
            title=request.title,
            text=request.text,
            source_uri=request.source_uri,
            metadata=request.metadata,
        )

        chunker = domain.chunker or self.default_chunker
        chunks = chunker.chunk(artifact)

        entities = []
        relationships = []
        signals = []
        actionable_items = []
        extractor_ids = []
        for extractor in domain.extractors:
            supported_artifact_type_ids = getattr(extractor, "artifact_type_ids", None)
            if (
                supported_artifact_type_ids is not None
                and request.artifact_type_id not in supported_artifact_type_ids
            ):
                continue
            extract_with_execution = getattr(extractor, "extract_with_execution", None)
            if extract_with_execution is not None:
                result = cast(
                    ExtractionResult,
                    cast(Callable[..., Any], extract_with_execution)(
                        artifact, chunks, self.execution_context
                    ),
                )
            else:
                result = extractor.extract(artifact, chunks)
            entities.extend(result.entities)
            relationships.extend(result.relationships)
            signals.extend(result.signals)
            actionable_items.extend(result.actionable_items)
            extractor_ids.append(extractor.id)

        for task_generator in domain.task_generators:
            generate_with_execution = getattr(
                task_generator, "generate_with_execution", None
            )
            if generate_with_execution is not None:
                actionable_items = cast(
                    list[ActionableItem],
                    cast(Callable[..., Any], generate_with_execution)(
                        artifact, chunks, actionable_items, self.execution_context
                    ),
                )
            else:
                actionable_items.extend(task_generator.generate(artifact))

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
        """Build and store one registered perspective from owner-scoped context."""
        view, artifacts = self._build_perspective(
            domain_id=domain_id,
            view_definition_id=view_definition_id,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        return self.repository.store_perspective_view(
            view=view,
            domain_id=domain_id,
            owner_type=owner_type,
            owner_id=owner_id,
            source_artifacts=artifacts,
        )

    def get_perspective(
        self,
        *,
        domain_id: str,
        view_definition_id: str,
        owner_type: OwnerType,
        owner_id: str,
        regenerate: bool = False,
    ) -> PerspectiveView:
        """Return a cached perspective view, regenerating only when requested."""
        artifacts = self.repository.list_artifacts(
            domain_id=domain_id,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        if not regenerate:
            cached = self.repository.get_perspective_view(
                domain_id=domain_id,
                owner_type=owner_type,
                owner_id=owner_id,
                view_definition_id=view_definition_id,
            )
            if cached is not None:
                return _with_stale_metadata(cached, artifacts)
        view, built_artifacts = self._build_perspective(
            domain_id=domain_id,
            view_definition_id=view_definition_id,
            owner_type=owner_type,
            owner_id=owner_id,
            artifacts=artifacts,
        )
        return self.repository.store_perspective_view(
            view=view,
            domain_id=domain_id,
            owner_type=owner_type,
            owner_id=owner_id,
            source_artifacts=built_artifacts,
        )

    def _build_perspective(
        self,
        *,
        domain_id: str,
        view_definition_id: str,
        owner_type: OwnerType,
        owner_id: str,
        artifacts: list[Artifact] | None = None,
    ) -> tuple[PerspectiveView, list[Artifact]]:
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

        artifacts = artifacts or self.repository.list_artifacts(
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
        build_with_execution = getattr(builder, "build_with_execution", None)
        if build_with_execution is not None:
            return (
                cast(
                    PerspectiveView,
                    cast(Callable[..., Any], build_with_execution)(
                        context, self.execution_context
                    ),
                ),
                artifacts,
            )
        return builder.build(context), artifacts


def _with_stale_metadata(
    view: PerspectiveView, current_artifacts: list[Artifact]
) -> PerspectiveView:
    """Annotate a cached view with source freshness metadata."""
    current_ids = [artifact.id for artifact in current_artifacts]
    stored_ids = view.metadata.get("source_artifact_ids")
    if not isinstance(stored_ids, list):
        stored_ids = []
    is_stale = current_ids != stored_ids
    view.metadata["is_stale"] = is_stale
    view.metadata["current_artifact_count"] = len(current_ids)
    view.metadata["source_artifact_count"] = len(stored_ids)
    if is_stale:
        view.metadata["stale_reason"] = (
            "Artifacts changed after this view was generated."
        )
    else:
        view.metadata.pop("stale_reason", None)
    return view
