"""Shared data structures for RAG services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EMBEDDING_DIMENSIONS = 384


@dataclass(frozen=True)
class ExtractedSection:
    """Extracted text and optional source location metadata."""

    text: str
    page_number: int | None = None
    source_location: str | None = None


@dataclass(frozen=True)
class PreparedRagChunk:
    """Chunk text with source metadata before embedding."""

    text: str
    chunk_index: int
    page_number: int | None
    source_location: str | None


@dataclass(frozen=True)
class RagVectorChunk:
    """One vectorized chunk ready for pgvector insertion."""

    chunk_text: str
    embedding: list[float]
    chunk_index: int
    page_number: int | None = None
    source_location: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class RagDocumentResult:
    """Stored document summary for API responses."""

    document_id: int
    source: str
    title: str | None
    labels: list[str]
    chunk_count: int
    reused_existing_document: bool = False


@dataclass(frozen=True)
class PreparedRagDocument:
    """Extracted document text ready for persistence and embedding."""

    source: str
    title: str | None
    content_sha256: str
    sections: list[ExtractedSection]
    combined_text: str


@dataclass(frozen=True)
class RagSearchResult:
    """A similarity result constrained by caller-selected labels."""

    chunk_id: int
    document_id: int
    source: str
    title: str | None
    chunk_index: int
    chunk_text: str
    distance: float
