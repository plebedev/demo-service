"""Default domain-neutral artifact chunking."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.context_engine.models import (
    Artifact,
    ArtifactChunk,
    SourceLink,
    new_context_id,
)


@dataclass(frozen=True)
class SimpleTextChunker:
    """Small deterministic text chunker for MVP ingestion."""

    chunk_size: int = 1200
    overlap: int = 120
    id: str = "simple-text-chunker"

    def __post_init__(self) -> None:
        """Validate chunking bounds."""
        if self.chunk_size < 1:
            raise ValueError("Chunk size must be positive.")
        if self.overlap < 0 or self.overlap >= self.chunk_size:
            raise ValueError("Chunk overlap must be smaller than chunk size.")

    def chunk(self, artifact: Artifact) -> list[ArtifactChunk]:
        """Split artifact text into source-linked chunks."""
        text = artifact.text
        if not text:
            return []

        chunks: list[ArtifactChunk] = []
        start = 0
        chunk_index = 0
        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            chunk_text = text[start:end]
            chunk_id = new_context_id("chunk")
            chunks.append(
                ArtifactChunk(
                    id=chunk_id,
                    artifact_id=artifact.id,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    start_offset=start,
                    end_offset=end,
                    source_link=SourceLink(
                        artifact_id=artifact.id,
                        chunk_id=chunk_id,
                        start_offset=start,
                        end_offset=end,
                        excerpt=chunk_text[:240],
                    ),
                )
            )
            if end == len(text):
                break
            start = end - self.overlap
            chunk_index += 1
        return chunks
