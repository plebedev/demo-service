"""Protected endpoints for local RAG document ingestion and search."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_access_token
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.rag import (
    RagDocumentIngestResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagSearchResultResponse,
)
from app.services.embeddings import EmbeddingProvider, build_embedding_provider
from app.services.rag_ingestion import RagIngestionService
from app.services.rag_store import RagStore

router = APIRouter(
    prefix="/api/rag",
    tags=["rag"],
    dependencies=[Depends(get_current_access_token)],
)


def get_rag_embedding_provider(
    settings: Settings = Depends(get_settings),
) -> EmbeddingProvider:
    """Build the request-scoped embedding provider."""
    return build_embedding_provider(settings)


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
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    embeddings: EmbeddingProvider = Depends(get_rag_embedding_provider),
) -> RagDocumentIngestResponse:
    """Chunk, embed, and persist one text/PDF document under labels."""
    service = RagIngestionService(store=RagStore(), embeddings=embeddings)
    try:
        result = await service.ingest_document(
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
    )


@router.post("/search", response_model=RagSearchResponse)
def search_rag_chunks_route(
    payload: RagSearchRequest,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    embeddings: EmbeddingProvider = Depends(get_rag_embedding_provider),
) -> RagSearchResponse:
    """Search nearest chunks within the requested labels."""
    try:
        store = RagStore()
        if db.get_bind().dialect.name == "oracle":
            results = store.search_chunks_with_oracle_query(
                db,
                labels=payload.labels,
                query=payload.query,
                oracle_model_name=settings.rag_oracle_embedding_model,
                limit=payload.limit,
            )
        else:
            query_embedding = embeddings.embed([payload.query])[0]
            results = store.search_chunks(
                db,
                labels=payload.labels,
                embedding=query_embedding,
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
