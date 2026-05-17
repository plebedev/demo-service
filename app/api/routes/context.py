"""Protected generic Context Engine endpoints."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_access_token
from app.core.context_engine.models import IngestionRequest, OwnerType
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.service import ContextEngineService
from app.core.context_engine.storage import ContextRepository
from app.core.security import AccessTokenClaims
from app.schemas.context import (
    ActionableItemListResponse,
    ContextArtifactCreateRequest,
    ContextArtifactIngestResponse,
    ContextSignalListResponse,
    DomainDetailResponse,
    DomainListResponse,
    DomainSummaryResponse,
)

router = APIRouter(prefix="/api/context", tags=["context"])


def get_context_registry(request: Request) -> DomainRegistry:
    """Return the app-scoped Context Engine domain registry."""
    return cast(DomainRegistry, request.app.state.context_domain_registry)


def get_context_engine(request: Request) -> ContextEngineService:
    """Return the app-scoped Context Engine service."""
    return cast(ContextEngineService, request.app.state.context_engine)


def get_context_repository(request: Request) -> ContextRepository:
    """Return the app-scoped Context Engine repository."""
    return cast(ContextRepository, request.app.state.context_repository)


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
        perspectives=registry.list_perspectives(domain_id),
        views=[view.id for view in registry.list_views(domain_id)],
    )


@router.post(
    "/domains/{domain_id}/artifacts",
    response_model=ContextArtifactIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_context_artifact(
    domain_id: str,
    payload: ContextArtifactCreateRequest,
    claims: AccessTokenClaims = Depends(get_current_access_token),
    service: ContextEngineService = Depends(get_context_engine),
) -> ContextArtifactIngestResponse:
    """Ingest one artifact through the generic Context Engine flow."""
    try:
        result = service.ingest_artifact(
            IngestionRequest(
                domain_id=domain_id,
                artifact_type_id=payload.artifact_type_id,
                owner_type=OwnerType.INVITATION_CODE,
                owner_id=str(claims.invitation_code_id),
                text=payload.text,
                title=payload.title,
                source_uri=payload.source_uri,
                metadata=payload.metadata,
            )
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return ContextArtifactIngestResponse(
        artifact=result.artifact,
        chunks=result.chunks,
        entities=result.entities,
        relationships=result.relationships,
        signals=result.signals,
        actionable_items=result.actionable_items,
        extractor_ids=result.extractor_ids,
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


@router.get("/domains/{domain_id}/tasks", response_model=ActionableItemListResponse)
def list_context_tasks(
    domain_id: str,
    claims: AccessTokenClaims = Depends(get_current_access_token),
    registry: DomainRegistry = Depends(get_context_registry),
    repository: ContextRepository = Depends(get_context_repository),
) -> ActionableItemListResponse:
    """Return caller-owned actionable items for a Context Engine domain."""
    try:
        registry.get_domain(domain_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context domain not found.",
        ) from exc
    return ActionableItemListResponse(
        tasks=repository.list_actionable_items(
            domain_id=domain_id,
            owner_type=OwnerType.INVITATION_CODE,
            owner_id=str(claims.invitation_code_id),
        )
    )
