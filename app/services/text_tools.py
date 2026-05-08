"""Optional client for the internal Rust text-tools sidecar."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.logging import log_event
from app.services.rag.models import ExtractedSection, PreparedRagChunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextToolsChunk:
    """Chunk shape returned by the Rust text-tools service."""

    index: int
    text: str
    bytes: int


class TextToolsClient:
    """Tiny HTTP client for deterministic text-tools calls."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.text_tools_base_url.rstrip("/")
        self.timeout = settings.text_tools_timeout_seconds

    def chunk_text(
        self,
        text: str,
        *,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[TextToolsChunk]:
        """Split text through the Rust sidecar."""
        response = httpx.post(
            f"{self.base_url}/v1/text/chunk",
            json={
                "text": text,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return [
            TextToolsChunk(
                index=int(item["index"]),
                text=str(item["text"]),
                bytes=int(item["bytes"]),
            )
            for item in payload.get("chunks", [])
        ]


class RagChunkFallback(Protocol):
    """Callable shape for the Python RAG chunking fallback."""

    def __call__(
        self,
        sections: list[ExtractedSection],
        *,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[PreparedRagChunk]:
        """Build RAG chunks with the local Python implementation."""


def build_rag_chunks_with_optional_text_tools(
    sections: list[ExtractedSection],
    *,
    settings: Settings,
    fallback: RagChunkFallback,
) -> list[PreparedRagChunk]:
    """Build RAG chunks with Rust sidecar when enabled, falling back to Python."""
    if not settings.text_tools_enabled:
        return fallback(
            sections,
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
        )

    try:
        client = TextToolsClient(settings)
        chunks: list[PreparedRagChunk] = []
        for section in sections:
            for text_chunk in client.chunk_text(
                section.text,
                chunk_size=settings.rag_chunk_size,
                chunk_overlap=settings.rag_chunk_overlap,
            ):
                chunks.append(
                    PreparedRagChunk(
                        text=text_chunk.text,
                        chunk_index=len(chunks),
                        page_number=section.page_number,
                        source_location=section.source_location,
                    )
                )
        log_event(
            logger,
            "text_tools_chunking_succeeded",
            text_tools_base_url=settings.text_tools_base_url,
            section_count=len(sections),
            chunk_count=len(chunks),
        )
        return chunks
    except Exception as exc:
        log_event(
            logger,
            "text_tools_chunking_failed",
            level=logging.WARNING,
            text_tools_base_url=settings.text_tools_base_url,
            error=str(exc),
        )
        return fallback(
            sections,
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
        )
