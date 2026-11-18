"""Protected generic Context Engine endpoints."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from typing import cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pypdf import PdfReader

from app.api.deps import get_current_access_token
from app.core.context_engine.errors import (
    ArtifactIngestionError,
    IdempotencyConflictError,
)
from app.core.context_engine.idempotency import (
    normalize_idempotency_key,
    request_fingerprint,
)
from app.core.context_engine.models import (
    ActionableItem,
    IngestionIdempotency,
    IngestionRequest,
    IngestionResult,
    OwnerType,
)
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.service import ContextEngineService
from app.core.context_engine.storage import ContextRepository
from app.core.security import AccessTokenClaims
from app.schemas.context import (
    ActionableItemCollectionResponse,
    ActionableItemListResponse,
    ContextArtifactBatchCreateRequest,
    ContextArtifactBatchIngestResponse,
    ContextArtifactCreateRequest,
    ContextArtifactDetailResponse,
    ContextArtifactIngestResponse,
    ContextArtifactListResponse,
    ContextSignalListResponse,
    DomainDetailResponse,
    DomainListResponse,
    DomainSummaryResponse,
    ExtensionSummaryResponse,
    PerspectiveViewResponse,
    ViewDefinitionResponse,
)

router = APIRouter(prefix="/api/context", tags=["context"])

SUPPORTED_TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
}
SUPPORTED_PDF_MIME_TYPES = {"application/pdf"}
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


def get_context_registry(request: Request) -> DomainRegistry:
    """Return the app-scoped Context Engine domain registry."""
    return cast(DomainRegistry, request.app.state.context_domain_registry)


def get_context_engine(request: Request) -> ContextEngineService:
    """Return the app-scoped Context Engine service."""
    return cast(ContextEngineService, request.app.state.context_engine)


def get_context_repository(request: Request) -> ContextRepository:
    """Return the app-scoped Context Engine repository."""
    return cast(ContextRepository, request.app.state.context_repository)


def _owner_actionable_items(
    *,
    domain_id: str,
    claims: AccessTokenClaims,
    registry: DomainRegistry,
    repository: ContextRepository,
) -> list[ActionableItem]:
    """Return caller-owned actionable items after validating the domain."""
    try:
        registry.get_domain(domain_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    return repository.list_actionable_items(
        domain_id=domain_id,
        owner_type=OwnerType.INVITATION_CODE,
        owner_id=str(claims.invitation_code_id),
    )


def _extract_upload_text(
    file_bytes: bytes, content_type: str | None, filename: str | None
) -> tuple[str, str | None]:
    """Extract demo-supported text from an uploaded artifact."""
    content_type = content_type or ""
    filename = filename or "uploaded artifact"
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if content_type in SUPPORTED_PDF_MIME_TYPES or suffix == "pdf":
        try:
            reader = PdfReader(BytesIO(file_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:  # pragma: no cover - parser-specific failure shape
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded PDF could not be read as extractable text.",
            ) from exc
        text = "\n\n".join(page.strip() for page in pages if page.strip()).strip()
        if not text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded PDF did not contain extractable text.",
            )
        return text, content_type

    if (
        content_type in SUPPORTED_TEXT_MIME_TYPES
        or content_type.startswith("text/")
        or suffix in {"txt", "md", "markdown", "csv", "json"}
    ):
        try:
            return file_bytes.decode("utf-8"), content_type
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded text file must be UTF-8 encoded.",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Only text files and extractable PDFs are supported.",
    )


def _ingestion_request(
    domain_id: str,
    claims: AccessTokenClaims,
    payload: ContextArtifactCreateRequest,
) -> IngestionRequest:
    """Map one API artifact payload to a caller-owned ingestion request."""
    return IngestionRequest(
        domain_id=domain_id,
        artifact_type_id=payload.artifact_type_id,
        owner_type=OwnerType.INVITATION_CODE,
        owner_id=str(claims.invitation_code_id),
        text=payload.text,
        title=payload.title,
        source_uri=payload.source_uri,
        metadata=payload.metadata,
    )


def _idempotency(
    idempotency_key: str | None, payload: object
) -> IngestionIdempotency | None:
    """Return validated idempotency input for an optional request header."""
    if idempotency_key is None:
        return None
    try:
        key = normalize_idempotency_key(idempotency_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return IngestionIdempotency(key=key, fingerprint=request_fingerprint(payload))


def _fingerprint_metadata(metadata_json: str | None) -> object:
    """Return canonical upload metadata for fingerprinting when it is JSON."""
    if metadata_json is None:
        return None
    try:
        return cast(object, json.loads(metadata_json))
    except json.JSONDecodeError:
        return metadata_json


def _idempotency_conflict(exc: IdempotencyConflictError) -> HTTPException:
    """Map an idempotency conflict to an HTTP 409 response."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _replay_ingestion(
    service: ContextEngineService,
    domain_id: str,
    claims: AccessTokenClaims,
    idempotency: IngestionIdempotency,
) -> list[IngestionResult] | None:
    """Return stored results for a caller-scoped idempotency key, if any."""
    try:
        return service.replay_idempotent_ingestion(
            domain_id=domain_id,
            owner_type=OwnerType.INVITATION_CODE,
            owner_id=str(claims.invitation_code_id),
            idempotency=idempotency,
        )
    except IdempotencyConflictError as exc:
        raise _idempotency_conflict(exc) from exc


def _ingest_requests(
    service: ContextEngineService,
    requests: list[IngestionRequest],
    idempotency: IngestionIdempotency | None,
    *,
    batch: bool = False,
) -> list[IngestionResult]:
    """Run atomic ingestion and map Context Engine errors to HTTP errors."""
    try:
        return service.ingest_artifacts(requests, idempotency=idempotency)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    except IdempotencyConflictError as exc:
        raise _idempotency_conflict(exc) from exc
    except ArtifactIngestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"artifacts[{exc.index}]: {exc}" if batch else str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _ingest_response(result: IngestionResult) -> ContextArtifactIngestResponse:
    """Map one ingestion result to the public API response model."""
    return ContextArtifactIngestResponse(
        artifact=result.artifact,
        chunks=result.chunks,
        entities=result.entities,
        relationships=result.relationships,
        signals=result.signals,
        actionable_items=result.actionable_items,
        extractor_ids=result.extractor_ids,
    )


@router.get("/domains", response_model=DomainListResponse)
def list_context_domains(
    _: AccessTokenClaims = Depends(get_current_access_token),
    registry: DomainRegistry = Depends(get_context_registry),
) -> DomainListResponse:
    """Return registered Context Engine domains."""
    return DomainListResponse(
        domains=[
            DomainSummaryResponse(
                id=domain.id,
                display_name=domain.display_name,
                metadata=domain.metadata,
            )
            for domain in registry.list_domains()
        ]
    )


@router.get("/domains/{domain_id}", response_model=DomainDetailResponse)
def get_context_domain(
    domain_id: str,
    _: AccessTokenClaims = Depends(get_current_access_token),
    registry: DomainRegistry = Depends(get_context_registry),
) -> DomainDetailResponse:
    """Return one registered Context Engine domain."""
    try:
        domain = registry.get_domain(domain_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    return DomainDetailResponse(
        id=domain.id,
        display_name=domain.display_name,
        metadata=domain.metadata,
        artifact_types=registry.list_artifact_types(domain_id),
        perspectives=[
            ExtensionSummaryResponse(id=perspective_id)
            for perspective_id in registry.list_perspectives(domain_id)
        ],
        views=[
            ViewDefinitionResponse(
                id=view.id,
                display_name=view.display_name,
                description=view.description,
                metadata=view.metadata,
            )
            for view in registry.list_views(domain_id)
        ],
    )


@router.post(
    "/domains/{domain_id}/artifacts",
    response_model=ContextArtifactIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_context_artifact(
    domain_id: str,
    payload: ContextArtifactCreateRequest,
    idempotency_key: str | None = Header(default=None, alias=IDEMPOTENCY_KEY_HEADER),
    claims: AccessTokenClaims = Depends(get_current_access_token),
    service: ContextEngineService = Depends(get_context_engine),
) -> ContextArtifactIngestResponse:
    """Ingest one artifact through the generic Context Engine flow."""
    idempotency = _idempotency(
        idempotency_key,
        {"operation": "artifact", "artifact": payload.model_dump(mode="json")},
    )
    results = _ingest_requests(
        service,
        [_ingestion_request(domain_id, claims, payload)],
        idempotency,
    )
    return _ingest_response(results[0])


@router.post(
    "/domains/{domain_id}/artifact-batches",
    response_model=ContextArtifactBatchIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_context_artifact_batch(
    domain_id: str,
    payload: ContextArtifactBatchCreateRequest,
    idempotency_key: str | None = Header(default=None, alias=IDEMPOTENCY_KEY_HEADER),
    claims: AccessTokenClaims = Depends(get_current_access_token),
    service: ContextEngineService = Depends(get_context_engine),
) -> ContextArtifactBatchIngestResponse:
    """Atomically ingest several artifacts, returning results in request order."""
    if idempotency_key is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{IDEMPOTENCY_KEY_HEADER} header is required for batch ingestion.",
        )
    idempotency = _idempotency(
        idempotency_key,
        {
            "operation": "artifact_batch",
            "artifacts": [
                artifact.model_dump(mode="json") for artifact in payload.artifacts
            ],
        },
    )
    results = _ingest_requests(
        service,
        [
            _ingestion_request(domain_id, claims, artifact)
            for artifact in payload.artifacts
        ],
        idempotency,
        batch=True,
    )
    return ContextArtifactBatchIngestResponse(
        results=[_ingest_response(result) for result in results]
    )


@router.post(
    "/domains/{domain_id}/artifact-uploads",
    response_model=ContextArtifactIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_context_artifact(
    domain_id: str,
    artifact_type_id: str = Form(...),
    title: str | None = Form(default=None),
    source_uri: str | None = Form(default=None),
    metadata_json: str | None = Form(default=None),
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias=IDEMPOTENCY_KEY_HEADER),
    claims: AccessTokenClaims = Depends(get_current_access_token),
    service: ContextEngineService = Depends(get_context_engine),
) -> ContextArtifactIngestResponse:
    """Upload and ingest one text or extractable PDF artifact."""
    file_bytes = await file.read()
    idempotency = _idempotency(
        idempotency_key,
        {
            "operation": "artifact_upload",
            "artifact_type_id": artifact_type_id,
            "title": title,
            "source_uri": source_uri,
            "metadata": _fingerprint_metadata(metadata_json),
            "file_name": file.filename,
            "content_type": file.content_type,
            "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
        },
    )
    if idempotency is not None:
        replayed = _replay_ingestion(service, domain_id, claims, idempotency)
        if replayed is not None:
            return _ingest_response(replayed[0])

    text, content_type = _extract_upload_text(
        file_bytes, file.content_type, file.filename
    )
    metadata = {}
    if metadata_json:
        try:
            parsed = json.loads(metadata_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="metadata_json must be valid JSON.",
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="metadata_json must be a JSON object.",
            )
        metadata = parsed
    metadata.setdefault("ingestion_method", "upload")
    metadata.setdefault("file_name", file.filename)
    metadata.setdefault("content_type", content_type)

    results = _ingest_requests(
        service,
        [
            IngestionRequest(
                domain_id=domain_id,
                artifact_type_id=artifact_type_id,
                owner_type=OwnerType.INVITATION_CODE,
                owner_id=str(claims.invitation_code_id),
                text=text,
                title=title or file.filename,
                source_uri=source_uri
                or (f"upload://{file.filename}" if file.filename else None),
                metadata=metadata,
            )
        ],
        idempotency,
    )
    return _ingest_response(results[0])


@router.get(
    "/domains/{domain_id}/artifacts",
    response_model=ContextArtifactListResponse,
)
def list_context_artifacts(
    domain_id: str,
    claims: AccessTokenClaims = Depends(get_current_access_token),
    registry: DomainRegistry = Depends(get_context_registry),
    repository: ContextRepository = Depends(get_context_repository),
) -> ContextArtifactListResponse:
    """Return caller-owned artifacts for a Context Engine domain."""
    try:
        registry.get_domain(domain_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    return ContextArtifactListResponse(
        artifacts=repository.list_artifacts(
            domain_id=domain_id,
            owner_type=OwnerType.INVITATION_CODE,
            owner_id=str(claims.invitation_code_id),
        )
    )


@router.get(
    "/domains/{domain_id}/artifacts/{artifact_id}",
    response_model=ContextArtifactDetailResponse,
)
def get_context_artifact(
    domain_id: str,
    artifact_id: str,
    claims: AccessTokenClaims = Depends(get_current_access_token),
    registry: DomainRegistry = Depends(get_context_registry),
    repository: ContextRepository = Depends(get_context_repository),
) -> ContextArtifactDetailResponse:
    """Return one caller-owned artifact with persisted chunks."""
    try:
        registry.get_domain(domain_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    artifact = repository.get_artifact(
        domain_id=domain_id,
        owner_type=OwnerType.INVITATION_CODE,
        owner_id=str(claims.invitation_code_id),
        artifact_id=artifact_id,
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context artifact not found.",
        )
    return ContextArtifactDetailResponse(
        artifact=artifact,
        chunks=repository.list_chunks_for_artifact(artifact.id),
    )


@router.get("/domains/{domain_id}/signals", response_model=ContextSignalListResponse)
def list_context_signals(
    domain_id: str,
    claims: AccessTokenClaims = Depends(get_current_access_token),
    registry: DomainRegistry = Depends(get_context_registry),
    repository: ContextRepository = Depends(get_context_repository),
) -> ContextSignalListResponse:
    """Return caller-owned signals for a Context Engine domain."""
    try:
        registry.get_domain(domain_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    return ContextSignalListResponse(
        signals=repository.list_signals(
            domain_id=domain_id,
            owner_type=OwnerType.INVITATION_CODE,
            owner_id=str(claims.invitation_code_id),
        )
    )


@router.get(
    "/domains/{domain_id}/tasks",
    response_model=ActionableItemListResponse,
    deprecated=True,
)
def list_context_tasks(
    domain_id: str,
    claims: AccessTokenClaims = Depends(get_current_access_token),
    registry: DomainRegistry = Depends(get_context_registry),
    repository: ContextRepository = Depends(get_context_repository),
) -> ActionableItemListResponse:
    """Return caller-owned actionable items for a Context Engine domain."""
    return ActionableItemListResponse(
        tasks=_owner_actionable_items(
            domain_id=domain_id,
            claims=claims,
            registry=registry,
            repository=repository,
        )
    )


@router.get(
    "/domains/{domain_id}/actionable-items",
    response_model=ActionableItemCollectionResponse,
)
def list_context_actionable_items(
    domain_id: str,
    claims: AccessTokenClaims = Depends(get_current_access_token),
    registry: DomainRegistry = Depends(get_context_registry),
    repository: ContextRepository = Depends(get_context_repository),
) -> ActionableItemCollectionResponse:
    """Return caller-owned actionable items for a Context Engine domain."""
    return ActionableItemCollectionResponse(
        actionable_items=_owner_actionable_items(
            domain_id=domain_id,
            claims=claims,
            registry=registry,
            repository=repository,
        ),
    )


@router.get(
    "/domains/{domain_id}/views/{view_definition_id}",
    response_model=PerspectiveViewResponse,
)
def get_context_view(
    domain_id: str,
    view_definition_id: str,
    regenerate: bool = Query(default=False),
    claims: AccessTokenClaims = Depends(get_current_access_token),
    service: ContextEngineService = Depends(get_context_engine),
) -> PerspectiveViewResponse:
    """Return a caller-owned perspective view, regenerating only on request."""
    try:
        view = service.get_perspective(
            domain_id=domain_id,
            view_definition_id=view_definition_id,
            owner_type=OwnerType.INVITATION_CODE,
            owner_id=str(claims.invitation_code_id),
            regenerate=regenerate,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return PerspectiveViewResponse(view=view)
