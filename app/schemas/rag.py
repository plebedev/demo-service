"""Pydantic schemas for protected RAG document and persona APIs."""

from datetime import datetime

from pydantic import BaseModel, Field


class RagDocumentIngestResponse(BaseModel):
    """Summary returned after a document has been chunked and embedded."""

    document_id: int
    source: str
    title: str | None
    labels: list[str]
    chunk_count: int
    reused_existing_document: bool = False


class RagSearchRequest(BaseModel):
    """Request body for label-constrained vector search."""

    query: str = Field(min_length=1, max_length=4000)
    labels: list[str] = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class RagSearchResultResponse(BaseModel):
    """One chunk returned from label-constrained vector search."""

    chunk_id: int
    document_id: int
    source: str
    title: str | None
    chunk_index: int
    chunk_text: str
    distance: float


class RagSearchResponse(BaseModel):
    """Search response wrapper."""

    results: list[RagSearchResultResponse]


class RagPersonaCreateRequest(BaseModel):
    """Payload for creating a RAG assistant persona."""

    name: str = Field(min_length=1, max_length=255)
    instructions: str = Field(min_length=1, max_length=8000)
    capabilities: str | None = Field(default=None, max_length=8000)
    tool_config: str | None = Field(default=None, max_length=8000)


class RagPersonaUpdateRequest(BaseModel):
    """Payload for updating a RAG assistant persona."""

    name: str = Field(min_length=1, max_length=255)
    instructions: str = Field(min_length=1, max_length=8000)
    capabilities: str | None = Field(default=None, max_length=8000)
    tool_config: str | None = Field(default=None, max_length=8000)


class RagPersonaResponse(BaseModel):
    """Serialized RAG assistant persona."""

    id: int
    name: str
    instructions: str
    capabilities: str | None
    tool_config: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RagPersonaListResponse(BaseModel):
    """List wrapper for tenant-scoped RAG personas."""

    personas: list[RagPersonaResponse]


class RagPersonaDocumentResponse(BaseModel):
    """Document linked to a RAG persona."""

    document_id: int
    source: str
    title: str | None
    display_name: str | None
    chunk_count: int
    linked_at: datetime


class RagPersonaDocumentListResponse(BaseModel):
    """Documents linked to one RAG persona."""

    documents: list[RagPersonaDocumentResponse]


class RagPersonaDocumentIngestResponse(BaseModel):
    """Response returned after linking or ingesting a persona document."""

    document: RagPersonaDocumentResponse
    reused_existing_document: bool
