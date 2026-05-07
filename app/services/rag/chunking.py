"""Local deterministic text chunking for RAG ingestion."""

from __future__ import annotations

from app.services.rag.extraction import normalize_text
from app.services.rag.models import ExtractedSection, PreparedRagChunk


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
    normalized = normalize_text(value)
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
