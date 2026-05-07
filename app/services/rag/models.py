"""Shared data structures for RAG services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EMBEDDING_DIMENSIONS = 384


@dataclass(frozen=True)
class ExtractedSection:
    """Extracted text and optional source location metadata."""

    text: str  # raw text content of the section
    page_number: int | None = (
        None  # page number within the source document, if available
    )
    source_location: str | None = None  # human-readable location label (e.g. 'page 3')


@dataclass(frozen=True)
class PreparedRagChunk:
    """Chunk text with source metadata before embedding."""

    text: str  # text content of the chunk
    chunk_index: int  # zero-based position of this chunk within the document
    page_number: int | None  # source page number when available
    source_location: str | None  # human-readable location label


@dataclass(frozen=True)
class RagVectorChunk:
    """One vectorized chunk ready for pgvector insertion."""

    chunk_text: str  # text content of the chunk
    embedding: list[float]  # embedding vector produced by the embedding model
    chunk_index: int  # zero-based position within the document
    page_number: int | None = None  # source page number when available
    source_location: str | None = None  # human-readable location label
    metadata: dict[str, Any] | None = None  # optional per-chunk metadata


@dataclass(frozen=True)
class RagDocumentResult:
    """Stored document summary for API responses."""

    document_id: int  # database ID of the stored document
    source: str  # original filename or URL of the document
    title: str | None  # optional display title
    labels: list[str]  # search labels assigned to the document
    chunk_count: int  # number of chunks created during ingestion
    reused_existing_document: bool = (
        False  # True when a content hash match skipped re-ingestion
    )


@dataclass(frozen=True)
class PreparedRagDocument:
    """Extracted document text ready for persistence and embedding."""

    source: str  # original filename or URL
    title: str | None  # optional display title
    content_sha256: str  # SHA-256 hash of the combined text for deduplication
    sections: list[ExtractedSection]  # ordered list of extracted sections
    combined_text: str  # full text passed to the chunking step


@dataclass(frozen=True)
class RagSearchResult:
    """A similarity result constrained by caller-selected labels."""

    chunk_id: int  # database ID of the matched chunk
    document_id: int  # database ID of the parent document
    source: str  # source filename or URL
    title: str | None  # optional document display title
    chunk_index: int  # zero-based position of the chunk within its document
    chunk_text: str  # text content of the matched chunk
    distance: float  # cosine distance; lower means more similar to the query
