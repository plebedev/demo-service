"""Local/Postgres RAG strategy using Ollama and pgvector."""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.embeddings import EmbeddingProvider
from app.services.rag.chunking import build_rag_chunks, split_text_into_chunks
from app.services.rag.models import (
    EMBEDDING_DIMENSIONS,
    PreparedRagDocument,
    PreparedRagChunk,
    RagDocumentResult,
    RagSearchResult,
    RagVectorChunk,
)
from app.services.rag.repository import RagDocumentRepository


class LocalPostgresRagStrategy:
    """RAG implementation for local Postgres with pgvector."""

    def __init__(
        self,
        *,
        embeddings: EmbeddingProvider,
        repository: RagDocumentRepository | None = None,
    ) -> None:
        self.embeddings = embeddings
        self.repository = repository or RagDocumentRepository()

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
    ) -> RagDocumentResult:
        """Extract, chunk locally, embed with Ollama, and store pgvector chunks."""
        prepared = await self.repository.prepare_document(
            input_text=input_text,
            file=file,
            source=source,
            title=title,
        )
        return self.create_document_from_prepared(
            session,
            settings=settings,
            prepared=prepared,
            labels=labels,
        )

    def create_document_from_prepared(
        self,
        session: Session,
        *,
        settings: Settings,
        prepared: PreparedRagDocument,
        labels: list[str],
    ) -> RagDocumentResult:
        """Chunk, embed, and persist an already extracted document."""
        prepared_chunks = build_rag_chunks(
            prepared.sections,
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
        )
        if not prepared_chunks:
            raise ValueError("No extractable text was available for RAG ingestion.")

        chunks = self._embed_prepared_chunks(prepared_chunks, settings=settings)
        for chunk in chunks:
            self._validate_vector_chunk(chunk)

        document = self.repository.create_document(
            session,
            source=prepared.source,
            title=prepared.title,
            labels=labels,
            content_sha256=prepared.content_sha256,
        )
        for chunk in chunks:
            self._insert_chunk(session, document.id, chunk)
        session.commit()

        return RagDocumentResult(
            document_id=document.id,
            source=document.source,
            title=document.title,
            labels=[label.label_key for label in document.labels],
            chunk_count=len(chunks),
        )

    def _embed_prepared_chunks(
        self,
        prepared_chunks: list[PreparedRagChunk],
        *,
        settings: Settings,
    ) -> list[RagVectorChunk]:
        """Embed chunks one at a time, splitting only chunks that exceed context."""
        chunks: list[RagVectorChunk] = []
        pending = list(prepared_chunks)
        while pending:
            chunk = pending.pop(0)
            try:
                embeddings = self.embeddings.embed([chunk.text])
            except RuntimeError as exc:
                if self._should_split_embedding_input(exc, chunk.text):
                    pending = [
                        *self._split_prepared_chunk_for_retry(chunk, settings=settings),
                        *pending,
                    ]
                    continue
                raise
            if len(embeddings) != 1:
                raise RuntimeError(
                    "Embedding provider returned an unexpected number of vectors."
                )
            chunks.append(
                RagVectorChunk(
                    chunk_text=chunk.text,
                    embedding=embeddings[0],
                    chunk_index=len(chunks),
                    page_number=chunk.page_number,
                    source_location=chunk.source_location,
                )
            )
        return chunks

    def _should_split_embedding_input(self, exc: RuntimeError, text: str) -> bool:
        message = str(exc).lower()
        if len(text) <= 100:
            return False
        return (
            "context length" in message
            or "input length" in message
            or "too long" in message
        )

    def _split_prepared_chunk_for_retry(
        self,
        chunk: PreparedRagChunk,
        *,
        settings: Settings,
    ) -> list[PreparedRagChunk]:
        split_size = max(100, min(settings.rag_chunk_size, len(chunk.text) // 2))
        split_overlap = min(settings.rag_chunk_overlap, max(0, split_size // 10))
        text_chunks = split_text_into_chunks(
            chunk.text,
            chunk_size=split_size,
            chunk_overlap=split_overlap,
        )
        if len(text_chunks) <= 1:
            raise RuntimeError("RAG chunk exceeded embedding context length.")
        return [
            PreparedRagChunk(
                text=text_chunk,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                source_location=chunk.source_location,
            )
            for text_chunk in text_chunks
        ]

    def search(
        self,
        session: Session,
        *,
        settings: Settings,
        labels: list[str],
        query: str,
        limit: int,
    ) -> list[RagSearchResult]:
        """Embed the query with Ollama and search pgvector chunks."""
        del settings
        normalized_labels = self.repository.normalize_labels(labels)
        if not normalized_labels:
            raise ValueError("At least one RAG label is required.")
        if not query.strip():
            raise ValueError("RAG search query cannot be empty.")
        if limit < 1:
            raise ValueError("Search limit must be at least 1.")

        embedding = self.embeddings.embed([query])[0]
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Embedding must have {EMBEDDING_DIMENSIONS} dimensions; "
                f"received {len(embedding)}."
            )

        label_params = {
            f"label_{index}": label_key
            for index, label_key in enumerate(normalized_labels)
        }
        label_placeholders = ", ".join(f":{key}" for key in label_params)
        sql = text(
            f"""
            SELECT
                c.id AS chunk_id,
                d.id AS document_id,
                d.source AS source,
                d.title AS title,
                c.chunk_index AS chunk_index,
                c.chunk_text AS chunk_text,
                c.embedding <=> CAST(:embedding AS vector) AS distance
            FROM rag_document_chunks c
            JOIN rag_documents d ON d.id = c.document_id
            WHERE EXISTS (
                SELECT 1
                FROM rag_document_labels dl
                JOIN rag_labels l ON l.id = dl.label_id
                WHERE dl.document_id = d.id
                  AND l.label_key IN ({label_placeholders})
            )
            ORDER BY distance ASC
            LIMIT :limit
            """
        )
        rows = session.execute(
            sql,
            {
                "embedding": self._embedding_literal(embedding),
                "limit": limit,
                **label_params,
            },
        ).mappings()
        return [self._search_result(row) for row in rows]

    def search_persona_documents(
        self,
        session: Session,
        *,
        settings: Settings,
        persona_id: int,
        query: str,
        limit: int,
    ) -> list[RagSearchResult]:
        """Embed the query and search only chunks linked to one persona."""
        del settings
        if persona_id < 1:
            raise ValueError("RAG persona id must be positive.")
        if not query.strip():
            raise ValueError("RAG search query cannot be empty.")
        if limit < 1:
            raise ValueError("Search limit must be at least 1.")

        embedding = self.embeddings.embed([query])[0]
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Embedding must have {EMBEDDING_DIMENSIONS} dimensions; "
                f"received {len(embedding)}."
            )

        sql = text(
            """
            SELECT
                c.id AS chunk_id,
                d.id AS document_id,
                d.source AS source,
                d.title AS title,
                c.chunk_index AS chunk_index,
                c.chunk_text AS chunk_text,
                c.embedding <=> CAST(:embedding AS vector) AS distance
            FROM rag_document_chunks c
            JOIN rag_documents d ON d.id = c.document_id
            JOIN rag_persona_documents pd ON pd.document_id = d.id
            WHERE pd.persona_id = :persona_id
            ORDER BY distance ASC
            LIMIT :limit
            """
        )
        rows = session.execute(
            sql,
            {
                "embedding": self._embedding_literal(embedding),
                "persona_id": persona_id,
                "limit": limit,
            },
        ).mappings()
        return [self._search_result(row) for row in rows]

    def _insert_chunk(
        self,
        session: Session,
        document_id: int,
        chunk: RagVectorChunk,
    ) -> None:
        sql = text(
            """
            INSERT INTO rag_document_chunks (
                document_id,
                chunk_index,
                page_number,
                source_location,
                chunk_text,
                metadata_json,
                embedding
            )
            VALUES (
                :document_id,
                :chunk_index,
                :page_number,
                :source_location,
                :chunk_text,
                :metadata_json,
                CAST(:embedding AS vector)
            )
            """
        )
        session.execute(
            sql,
            {
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "source_location": chunk.source_location,
                "chunk_text": chunk.chunk_text,
                "metadata_json": self.repository.serialize_json(chunk.metadata),
                "embedding": self._embedding_literal(chunk.embedding),
            },
        )

    def _validate_vector_chunk(self, chunk: RagVectorChunk) -> None:
        if not chunk.chunk_text.strip():
            raise ValueError("RAG chunk text cannot be empty.")
        if chunk.chunk_index < 0:
            raise ValueError("RAG chunk index cannot be negative.")
        if len(chunk.embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Embedding must have {EMBEDDING_DIMENSIONS} dimensions; "
                f"received {len(chunk.embedding)}."
            )

    def _embedding_literal(self, embedding: list[float]) -> str:
        return "[" + ",".join(str(float(value)) for value in embedding) + "]"

    def _search_result(self, row: RowMapping) -> RagSearchResult:
        return RagSearchResult(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            source=row["source"],
            title=row["title"],
            chunk_index=row["chunk_index"],
            chunk_text=row["chunk_text"],
            distance=float(row["distance"]),
        )
