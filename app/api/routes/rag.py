"""Protected endpoints for RAG document ingestion and search."""

from __future__ import annotations

from typing import Annotated
from typing import Any, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_experience_access
from app.core.config import Settings, get_settings
from app.core.experiences import ExperienceId
from app.core.security import AccessTokenClaims
from app.db.session import get_db_session
from app.models.rag import RagDocument, RagPersona, RagPersonaDocument
from app.schemas.rag import (
    RagDocumentIngestResponse,
    RagPersonaDocumentIngestResponse,
    RagPersonaDocumentListResponse,
    RagPersonaDocumentResponse,
    RagPersonaCreateRequest,
    RagPersonaListResponse,
    RagPersonaResponse,
    RagPersonaUpdateRequest,
    RagSearchRequest,
    RagSearchResponse,
    RagSearchResultResponse,
)
from app.services.rag.factory import build_rag_service
from app.services.rag.repository import RagDocumentRepository
from app.services.rag.strategy import RagService

router = APIRouter(
    prefix="/api/rag",
    tags=["rag"],
)

rag_access = require_experience_access(ExperienceId.RAG_DEMO)
rag_repository = RagDocumentRepository()


def get_rag_service(
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> RagService:
    """Build the request-scoped RAG service for the active backend."""
    return build_rag_service(db, settings)


def _normalize_persona_name(name: str) -> str:
    """Normalize persona names for stable tenant-local uniqueness."""
    return " ".join(name.strip().split()).lower()


def _clean_optional_text(value: str | None) -> str | None:
    """Trim optional text fields and store empty values as null."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _serialize_persona(persona: RagPersona) -> RagPersonaResponse:
    """Convert a persona ORM row into the public response schema."""
    return RagPersonaResponse(
        id=persona.id,
        name=persona.name,
        instructions=persona.instructions,
        capabilities=persona.capabilities_serialized,
        tool_config=persona.tool_config_serialized,
        is_active=persona.is_active,
        created_at=persona.created_at,
        updated_at=persona.updated_at,
    )


def _serialize_persona_document(
    link: RagPersonaDocument,
    db: Session,
) -> RagPersonaDocumentResponse:
    """Convert a persona-document link into API shape."""
    document = link.document
    return RagPersonaDocumentResponse(
        document_id=document.id,
        source=document.source,
        title=document.title,
        display_name=link.display_name,
        chunk_count=rag_repository.document_chunk_count(db, document.id),
        linked_at=link.created_at,
    )


def _get_active_persona_or_404(
    db: Session,
    *,
    persona_id: int,
    invitation_code_id: int,
) -> RagPersona:
    """Return one active persona in the caller's tenant namespace."""
    persona = db.scalar(
        select(RagPersona).where(
            RagPersona.id == persona_id,
            RagPersona.invitation_code_id == invitation_code_id,
            RagPersona.is_active == True,
        )
    )
    if persona is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found.",
        )
    return persona


def _ensure_persona_name_available(
    db: Session,
    *,
    invitation_code_id: int,
    name_key: str,
    persona_id: int | None = None,
) -> None:
    """Reject duplicate active persona names inside one invitation namespace."""
    query = select(RagPersona.id).where(
        RagPersona.invitation_code_id == invitation_code_id,
        RagPersona.name_key == name_key,
        RagPersona.is_active == True,
    )
    if persona_id is not None:
        query = query.where(RagPersona.id != persona_id)
    existing_id = db.scalar(query)
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active persona with this name already exists.",
        )


@router.get("/personas", response_model=RagPersonaListResponse)
def list_rag_personas_route(
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> RagPersonaListResponse:
    """List active personas for the caller's invitation namespace."""
    personas = db.scalars(
        select(RagPersona)
        .where(
            RagPersona.invitation_code_id == claims.invitation_code_id,
            RagPersona.is_active == True,
        )
        .order_by(func.lower(RagPersona.name), RagPersona.id)
    ).all()
    return RagPersonaListResponse(
        personas=[_serialize_persona(persona) for persona in personas]
    )


@router.post(
    "/personas",
    response_model=RagPersonaResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_rag_persona_route(
    payload: RagPersonaCreateRequest,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> RagPersonaResponse:
    """Create a tenant-scoped RAG assistant persona."""
    name = " ".join(payload.name.strip().split())
    name_key = _normalize_persona_name(name)
    _ensure_persona_name_available(
        db, invitation_code_id=claims.invitation_code_id, name_key=name_key
    )
    persona = RagPersona(
        invitation_code_id=claims.invitation_code_id,
        name=name,
        name_key=name_key,
        instructions=payload.instructions.strip(),
        capabilities_serialized=_clean_optional_text(payload.capabilities),
        tool_config_serialized=_clean_optional_text(payload.tool_config),
        is_active=True,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return _serialize_persona(persona)


@router.get("/personas/{persona_id}", response_model=RagPersonaResponse)
def get_rag_persona_route(
    persona_id: int,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> RagPersonaResponse:
    """Return one active persona from the caller's invitation namespace."""
    return _serialize_persona(
        _get_active_persona_or_404(
            db,
            persona_id=persona_id,
            invitation_code_id=claims.invitation_code_id,
        )
    )


@router.put("/personas/{persona_id}", response_model=RagPersonaResponse)
def update_rag_persona_route(
    persona_id: int,
    payload: RagPersonaUpdateRequest,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> RagPersonaResponse:
    """Update an active persona in the caller's invitation namespace."""
    persona = _get_active_persona_or_404(
        db,
        persona_id=persona_id,
        invitation_code_id=claims.invitation_code_id,
    )
    name = " ".join(payload.name.strip().split())
    name_key = _normalize_persona_name(name)
    _ensure_persona_name_available(
        db,
        invitation_code_id=claims.invitation_code_id,
        name_key=name_key,
        persona_id=persona.id,
    )
    persona.name = name
    persona.name_key = name_key
    persona.instructions = payload.instructions.strip()
    persona.capabilities_serialized = cast(
        Any, _clean_optional_text(payload.capabilities)
    )
    persona.tool_config_serialized = cast(
        Any, _clean_optional_text(payload.tool_config)
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return _serialize_persona(persona)


@router.delete("/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rag_persona_route(
    persona_id: int,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> None:
    """Soft-delete a persona in the caller's invitation namespace."""
    persona = _get_active_persona_or_404(
        db,
        persona_id=persona_id,
        invitation_code_id=claims.invitation_code_id,
    )
    persona.is_active = False
    db.add(persona)
    db.commit()


@router.get(
    "/personas/{persona_id}/documents",
    response_model=RagPersonaDocumentListResponse,
)
def list_rag_persona_documents_route(
    persona_id: int,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> RagPersonaDocumentListResponse:
    """List documents linked to one persona in the caller's namespace."""
    persona = _get_active_persona_or_404(
        db,
        persona_id=persona_id,
        invitation_code_id=claims.invitation_code_id,
    )
    links = db.scalars(
        select(RagPersonaDocument)
        .where(RagPersonaDocument.persona_id == persona.id)
        .order_by(RagPersonaDocument.created_at.desc())
    ).all()
    return RagPersonaDocumentListResponse(
        documents=[_serialize_persona_document(link, db) for link in links]
    )


@router.post(
    "/personas/{persona_id}/documents",
    response_model=RagPersonaDocumentIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_rag_persona_document_route(
    persona_id: int,
    source: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    input_text: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    rag: RagService = Depends(get_rag_service),
) -> RagPersonaDocumentIngestResponse:
    """Upload or reuse a document and link it to a tenant-scoped persona."""
    persona = _get_active_persona_or_404(
        db,
        persona_id=persona_id,
        invitation_code_id=claims.invitation_code_id,
    )
    try:
        prepared = await rag_repository.prepare_document(
            input_text=input_text,
            file=file,
            source=source,
            title=title,
        )
        document = rag_repository.get_document_by_hash(db, prepared.content_sha256)
        reused_existing_document = document is not None
        if document is None:
            result = rag.create_document_from_prepared(
                db,
                settings=settings,
                prepared=prepared,
                labels=[f"persona-{persona.id}"],
            )
            document = db.get(RagDocument, result.document_id)
            if document is None:
                raise RuntimeError("RAG document was not persisted.")
        link = rag_repository.link_persona_document(
            db,
            persona_id=persona.id,
            document=document,
            display_name=prepared.title or prepared.source,
        )
        db.commit()
        db.refresh(link)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return RagPersonaDocumentIngestResponse(
        document=_serialize_persona_document(link, db),
        reused_existing_document=reused_existing_document,
    )


@router.delete(
    "/personas/{persona_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unlink_rag_persona_document_route(
    persona_id: int,
    document_id: int,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> None:
    """Remove a document from one persona without deleting chunks."""
    persona = _get_active_persona_or_404(
        db,
        persona_id=persona_id,
        invitation_code_id=claims.invitation_code_id,
    )
    removed = rag_repository.unlink_persona_document(
        db,
        persona_id=persona.id,
        document_id=document_id,
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona document not found.",
        )
    db.commit()


@router.post(
    "/documents",
    response_model=RagDocumentIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_rag_document_route(
    labels: Annotated[list[str], Form()],
    source: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    input_text: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    _: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    rag: RagService = Depends(get_rag_service),
) -> RagDocumentIngestResponse:
    """Chunk, embed, and persist one text/PDF document under labels."""
    try:
        result = await rag.ingest_document(
            db,
            settings=settings,
            labels=labels,
            source=source,
            title=title,
            input_text=input_text,
            file=file,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return RagDocumentIngestResponse(
        document_id=result.document_id,
        source=result.source,
        title=result.title,
        labels=result.labels,
        chunk_count=result.chunk_count,
        reused_existing_document=result.reused_existing_document,
    )


@router.post("/search", response_model=RagSearchResponse)
def search_rag_chunks_route(
    payload: RagSearchRequest,
    _: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    rag: RagService = Depends(get_rag_service),
) -> RagSearchResponse:
    """Search nearest chunks within the requested labels."""
    try:
        results = rag.search(
            db,
            settings=settings,
            labels=payload.labels,
            query=payload.query,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return RagSearchResponse(
        results=[
            RagSearchResultResponse(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                source=result.source,
                title=result.title,
                chunk_index=result.chunk_index,
                chunk_text=result.chunk_text,
                distance=result.distance,
            )
            for result in results
        ]
    )
