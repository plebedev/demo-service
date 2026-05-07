"""Document extraction and chunking for local RAG ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re

from fastapi import UploadFile
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.embeddings import EmbeddingProvider
from app.services.rag_store import RagChunkInput, RagStore


SUPPORTED_TEXT_MIME_TYPES = {"text/plain"}
SUPPORTED_PDF_MIME_TYPES = {"application/pdf"}


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
class RagIngestionResult:
    """Stored document summary for API responses."""

    document_id: int
    source: str
    title: str | None
    labels: list[str]
    chunk_count: int


class RagIngestionService:
    """Extract, chunk, embed, and persist one labeled RAG document."""

    def __init__(self, *, store: RagStore, embeddings: EmbeddingProvider) -> None:
        self.store = store
        self.embeddings = embeddings

    async def ingest_document(
        self,
        session: Session,
        *,
        settings: Settings,
        labels: list[str],
        source: str | None,
        title: str | None,
        input_text: str | None,
        file: UploadFile | None,
    ) -> RagIngestionResult:
        """Ingest one text/PDF document into the vector store."""
        sections, resolved_source = await extract_sections(
            input_text=input_text,
            file=file,
            fallback_source=source,
        )
        prepared_chunks = build_rag_chunks(
            sections,
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
        )
        if not prepared_chunks:
            raise ValueError("No extractable text was available for RAG ingestion.")

        embeddings = self.embeddings.embed([chunk.text for chunk in prepared_chunks])
        chunk_inputs = [
            RagChunkInput(
                chunk_text=chunk.text,
                embedding=embedding,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                source_location=chunk.source_location,
            )
            for chunk, embedding in zip(prepared_chunks, embeddings)
        ]
        document = self.store.create_document(
            session,
            source=resolved_source,
            title=title,
            labels=labels,
            chunks=chunk_inputs,
        )
        session.commit()

        return RagIngestionResult(
            document_id=document.id,
            source=document.source,
            title=document.title,
            labels=[label.label_key for label in document.labels],
            chunk_count=len(chunk_inputs),
        )


async def extract_sections(
    *,
    input_text: str | None,
    file: UploadFile | None,
    fallback_source: str | None,
) -> tuple[list[ExtractedSection], str]:
    """Extract text sections from pasted text or one supported upload."""
    normalized_input_text = _normalize_text(input_text)
    if normalized_input_text:
        return (
            [ExtractedSection(text=normalized_input_text)],
            fallback_source or "pasted-text",
        )

    if file is None:
        raise ValueError("Provide either input_text or a text/PDF file.")

    file_name = file.filename or "uploaded-document"
    content_type = file.content_type or "application/octet-stream"
    file_bytes = await file.read()
    if not file_bytes:
        raise ValueError("Uploaded document was empty.")

    suffix = Path(file_name).suffix.lower()
    if content_type in SUPPORTED_TEXT_MIME_TYPES or suffix == ".txt":
        sections = [_extract_text_file(file_bytes)]
    elif content_type in SUPPORTED_PDF_MIME_TYPES or suffix == ".pdf":
        sections = _extract_pdf_sections(file_bytes)
    else:
        raise ValueError(
            "Only pasted text, .txt files, and extractable PDFs are supported."
        )

    return sections, fallback_source or file_name


def build_rag_chunks(
    sections: list[ExtractedSection],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[PreparedRagChunk]:
    """Split extracted sections into stable overlapping chunks."""
    if chunk_size < 100:
        raise ValueError("RAG chunk size must be at least 100 characters.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            "RAG chunk overlap must be non-negative and smaller than size."
        )

    chunks: list[PreparedRagChunk] = []
    for section in sections:
        for text_chunk in _recursive_character_chunks(
            section.text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ):
            chunks.append(
                PreparedRagChunk(
                    text=text_chunk,
                    chunk_index=len(chunks),
                    page_number=section.page_number,
                    source_location=section.source_location,
                )
            )
    return chunks


def _recursive_character_chunks(
    value: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    normalized = _normalize_text(value)
    if normalized is None:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        hard_end = min(start + chunk_size, len(normalized))
        end = _find_split_point(normalized, start, hard_end)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


def _find_split_point(value: str, start: int, hard_end: int) -> int:
    if hard_end >= len(value):
        return hard_end

    window = value[start:hard_end]
    for pattern in ("\n\n", "\n", ". ", " "):
        index = window.rfind(pattern)
        minimum = max(1, int(len(window) * 0.5))
        if index >= minimum:
            return start + index + len(pattern)
    return hard_end


def _extract_text_file(file_bytes: bytes) -> ExtractedSection:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Text files must be UTF-8 encoded.") from exc

    normalized = _normalize_text(text)
    if normalized is None:
        raise ValueError("Text file did not contain extractable text.")
    return ExtractedSection(text=normalized)


def _extract_pdf_sections(file_bytes: bytes) -> list[ExtractedSection]:
    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError("PDF could not be opened.") from exc

    sections = []
    for index, page in enumerate(reader.pages, start=1):
        text = _normalize_text(page.extract_text() or "")
        if text:
            sections.append(
                ExtractedSection(
                    text=text,
                    page_number=index,
                    source_location=f"page {index}",
                )
            )

    if not sections:
        raise ValueError("PDF did not contain extractable text. OCR is not supported.")
    return sections


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None
