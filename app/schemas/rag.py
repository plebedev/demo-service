"""Pydantic schemas for protected RAG document APIs."""

from pydantic import BaseModel, Field


class RagDocumentIngestResponse(BaseModel):
    """Summary returned after a document has been chunked and embedded."""

    document_id: int
    source: str
    title: str | None
    labels: list[str]
    chunk_count: int


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
