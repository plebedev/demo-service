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
from app.models.rag import (
    RagConversation,
    RagDocument,
    RagMessage,
    RagMessageCitation,
    RagPersona,
    RagPersonaDocument,
)
from app.schemas.rag import (
    RagConversationMessageRequest,
    RagConversationMessageResponse,
    RagConversationCreateRequest,
    RagConversationDetailResponse,
    RagConversationListResponse,
    RagConversationResponse,
    RagDocumentIngestResponse,
    RagMessageCitationResponse,
    RagMessageResponse,
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
from app.services.rag.chat import RagAssistantDraft, RagChatService, RagTurnPlan
from app.services.rag.models import RagSearchResult
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


def get_rag_chat_service() -> RagChatService:
    """Build the request-scoped RAG chat service."""
    return RagChatService()


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


def _serialize_message(message: RagMessage) -> RagMessageResponse:
    """Convert a stored RAG message into API shape."""
    return RagMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        turn_index=message.turn_index,
        metadata=message.metadata_serialized,
        created_at=message.created_at,
    )


def _serialize_citation(citation: RagMessageCitation) -> RagMessageCitationResponse:
    """Convert a stored RAG citation into API shape."""
    return RagMessageCitationResponse(
        id=citation.id,
        message_id=citation.message_id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        chunk_index=citation.chunk_index,
        source=citation.source,
        title=citation.title,
        snippet=citation.snippet,
        rank=citation.rank,
    )


def _serialize_conversation(
    conversation: RagConversation,
) -> RagConversationResponse:
    """Convert a stored RAG conversation into API shape."""
    persona = conversation.persona
    return RagConversationResponse(
        id=conversation.id,
        persona_id=conversation.persona_id,
        persona_name=persona.name if persona is not None else None,
        title=conversation.title,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
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


def _get_conversation_or_404(
    db: Session,
    *,
    conversation_id: int,
    invitation_code_id: int,
) -> RagConversation:
    """Return one conversation in the caller's tenant namespace."""
    conversation = db.scalar(
        select(RagConversation).where(
            RagConversation.id == conversation_id,
            RagConversation.invitation_code_id == invitation_code_id,
        )
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return conversation


def _next_message_index(db: Session, conversation_id: int) -> int:
    """Return the next turn index for a conversation."""
    current = db.scalar(
        select(func.max(RagMessage.turn_index)).where(
            RagMessage.conversation_id == conversation_id
        )
    )
    return int(current) + 1 if current is not None else 0


def _user_turn_count(db: Session, conversation_id: int) -> int:
    """Return the number of user turns already stored."""
    return int(
        db.scalar(
            select(func.count(RagMessage.id)).where(
                RagMessage.conversation_id == conversation_id,
                RagMessage.role == "user",
            )
        )
        or 0
    )


def _message_metadata(value: dict[str, Any]) -> str:
    """Serialize message metadata into Oracle-compatible text."""
    serialized = rag_repository.serialize_json(value)
    return serialized or "{}"


def _citation_snippet(text: str) -> str:
    """Return a compact citation snippet."""
    normalized = " ".join(text.split())
    return normalized[:600]


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


@router.get("/conversations", response_model=RagConversationListResponse)
def list_rag_conversations_route(
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> RagConversationListResponse:
    """List conversations for the caller's invitation namespace."""
    conversations = db.scalars(
        select(RagConversation)
        .where(RagConversation.invitation_code_id == claims.invitation_code_id)
        .order_by(RagConversation.updated_at.desc(), RagConversation.id.desc())
    ).all()
    return RagConversationListResponse(
        conversations=[
            _serialize_conversation(conversation) for conversation in conversations
        ]
    )


@router.post(
    "/conversations",
    response_model=RagConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_rag_conversation_route(
    payload: RagConversationCreateRequest,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> RagConversationResponse:
    """Create a persona-scoped conversation in the caller's namespace."""
    persona = _get_active_persona_or_404(
        db,
        persona_id=payload.persona_id,
        invitation_code_id=claims.invitation_code_id,
    )
    conversation = RagConversation(
        invitation_code_id=claims.invitation_code_id,
        persona_id=persona.id,
        title=_clean_optional_text(payload.title),
        status="active",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _serialize_conversation(conversation)


@router.get(
    "/conversations/{conversation_id}",
    response_model=RagConversationDetailResponse,
)
def get_rag_conversation_route(
    conversation_id: int,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
) -> RagConversationDetailResponse:
    """Return one conversation and its stored messages."""
    conversation = _get_conversation_or_404(
        db,
        conversation_id=conversation_id,
        invitation_code_id=claims.invitation_code_id,
    )
    messages = db.scalars(
        select(RagMessage)
        .where(RagMessage.conversation_id == conversation.id)
        .order_by(RagMessage.turn_index, RagMessage.id)
    ).all()
    return RagConversationDetailResponse(
        conversation=_serialize_conversation(conversation),
        messages=[_serialize_message(message) for message in messages],
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=RagConversationMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rag_conversation_message_route(
    conversation_id: int,
    payload: RagConversationMessageRequest,
    claims: AccessTokenClaims = Depends(rag_access),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    rag: RagService = Depends(get_rag_service),
    chat: RagChatService = Depends(get_rag_chat_service),
) -> RagConversationMessageResponse:
    """Run one bounded RAG chat turn for a tenant-scoped conversation."""
    conversation = _get_conversation_or_404(
        db,
        conversation_id=conversation_id,
        invitation_code_id=claims.invitation_code_id,
    )
    if conversation.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation is not active.",
        )
    if conversation.persona_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation persona is no longer available.",
        )
    persona = _get_active_persona_or_404(
        db,
        persona_id=conversation.persona_id,
        invitation_code_id=claims.invitation_code_id,
    )
    existing_user_turns = _user_turn_count(db, conversation.id)
    if existing_user_turns >= 10:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RAG conversations are limited to 10 user turns.",
        )

    user_content = payload.content.strip()
    if not user_content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message content cannot be empty.",
        )
    recent_messages = db.scalars(
        select(RagMessage)
        .where(RagMessage.conversation_id == conversation.id)
        .order_by(RagMessage.turn_index.desc(), RagMessage.id.desc())
        .limit(8)
    ).all()
    recent_messages = list(reversed(recent_messages))

    plan = await chat.plan_turn(
        settings=settings,
        persona=persona,
        recent_messages=recent_messages,
        user_content=user_content,
    )
    retrieved_chunks = _retrieve_for_plan(
        db,
        settings=settings,
        rag=rag,
        persona_id=persona.id,
        plan=plan,
        user_content=user_content,
    )
    draft = await _draft_assistant_response(
        settings=settings,
        chat=chat,
        persona=persona,
        recent_messages=recent_messages,
        user_content=user_content,
        plan=plan,
        retrieved_chunks=retrieved_chunks,
    )

    next_index = _next_message_index(db, conversation.id)
    user_message = RagMessage(
        conversation_id=conversation.id,
        role="user",
        content=user_content,
        turn_index=next_index,
        metadata_serialized=None,
    )
    assistant_message = RagMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=draft.content_markdown,
        turn_index=next_index + 1,
        metadata_serialized=_message_metadata(
            {
                "plan": plan.model_dump(),
                "retrieved_chunk_ids": [chunk.chunk_id for chunk in retrieved_chunks],
            }
        ),
    )
    db.add(user_message)
    db.add(assistant_message)
    db.flush()

    citations = _store_citations(
        db,
        assistant_message=assistant_message,
        draft=draft,
        retrieved_chunks=retrieved_chunks,
    )
    db.add(conversation)
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    for citation in citations:
        db.refresh(citation)

    return RagConversationMessageResponse(
        user_message=_serialize_message(user_message),
        assistant_message=_serialize_message(assistant_message),
        citations=[_serialize_citation(citation) for citation in citations],
        turns_remaining=max(0, 10 - existing_user_turns - 1),
    )


def _retrieve_for_plan(
    db: Session,
    *,
    settings: Settings,
    rag: RagService,
    persona_id: int,
    plan: RagTurnPlan,
    user_content: str,
) -> list[RagSearchResult]:
    """Retrieve persona-scoped chunks for an allowed turn plan."""
    if not plan.is_allowed or not plan.needs_retrieval:
        return []
    queries = [query.strip() for query in plan.search_queries if query.strip()]
    if not queries:
        queries = [user_content]

    results: list[RagSearchResult] = []
    seen_chunk_ids: set[int] = set()
    for query in queries[:3]:
        for result in rag.search_persona_documents(
            db,
            settings=settings,
            persona_id=persona_id,
            query=query,
            limit=5,
        ):
            if result.chunk_id in seen_chunk_ids:
                continue
            results.append(result)
            seen_chunk_ids.add(result.chunk_id)
            if len(results) >= 5:
                return results
    return results


async def _draft_assistant_response(
    *,
    settings: Settings,
    chat: RagChatService,
    persona: RagPersona,
    recent_messages: list[RagMessage],
    user_content: str,
    plan: RagTurnPlan,
    retrieved_chunks: list[RagSearchResult],
) -> RagAssistantDraft:
    """Return either an off-topic refusal or a grounded assistant draft."""
    if not plan.is_allowed:
        return RagAssistantDraft(
            content_markdown=(
                plan.user_facing_refusal
                or "I can only help with questions that fit this persona."
            ),
            citation_chunk_ids=[],
        )
    return await chat.draft_answer(
        settings=settings,
        persona=persona,
        recent_messages=recent_messages,
        user_content=user_content,
        retrieved_chunks=retrieved_chunks,
    )


def _store_citations(
    db: Session,
    *,
    assistant_message: RagMessage,
    draft: RagAssistantDraft,
    retrieved_chunks: list[RagSearchResult],
) -> list[RagMessageCitation]:
    """Persist citations selected by the assistant draft."""
    if not retrieved_chunks:
        return []

    chunk_by_id = {chunk.chunk_id: chunk for chunk in retrieved_chunks}
    selected_ids = [
        chunk_id for chunk_id in draft.citation_chunk_ids if chunk_id in chunk_by_id
    ]
    if not selected_ids and draft.content_markdown.strip():
        selected_ids = [chunk.chunk_id for chunk in retrieved_chunks]

    citations: list[RagMessageCitation] = []
    for rank, chunk_id in enumerate(selected_ids[:5], start=1):
        chunk = chunk_by_id[chunk_id]
        citation = RagMessageCitation(
            message_id=assistant_message.id,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            source=chunk.source,
            title=chunk.title,
            snippet=_citation_snippet(chunk.chunk_text),
            rank=rank,
        )
        db.add(citation)
        citations.append(citation)
    db.flush()
    return citations


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
