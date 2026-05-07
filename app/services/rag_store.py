"""Persistence helpers for label-scoped RAG document chunks."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.rag import RagDocument, RagLabel


EMBEDDING_DIMENSIONS = 384


@dataclass(frozen=True)
class RagChunkInput:
    """One chunk ready to persist after extraction, chunking, and embedding."""

    chunk_text: str
    embedding: list[float]
    chunk_index: int
    page_number: int | None = None
    source_location: str | None = None
    metadata: dict[str, Any] | None = None


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


class RagStore:
    """Store and search RAG chunks with explicit label scoping."""

    def create_document(
        self,
        session: Session,
        *,
        source: str,
        labels: list[str],
        chunks: list[RagChunkInput],
        title: str | None = None,
        content_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RagDocument:
        """Create one document, assign labels, and insert vector-backed chunks."""
        normalized_labels = self._normalize_labels(labels)
        if not normalized_labels:
            raise ValueError("At least one RAG label is required.")
        if not chunks:
            raise ValueError("At least one RAG chunk is required.")

        for chunk in chunks:
            self._validate_chunk(chunk)

        document = RagDocument(
            source=source,
            title=title,
            content_sha256=content_sha256,
            metadata_serialized=self._serialize_json(metadata),
        )
        document.labels = [
            self._get_or_create_label(session, label_key)
            for label_key in normalized_labels
        ]
        session.add(document)
        session.flush()

        dialect_name = session.get_bind().dialect.name
        for chunk in chunks:
            self._insert_chunk(session, dialect_name, document.id, chunk)

        session.flush()
        return document

    def search_chunks(
        self,
        session: Session,
        *,
        labels: list[str],
        embedding: list[float],
        limit: int = 5,
    ) -> list[RagSearchResult]:
        """Return nearest chunks from documents carrying any requested label."""
        normalized_labels = self._normalize_labels(labels)
        if not normalized_labels:
            raise ValueError("At least one RAG label is required.")
        self._validate_embedding(embedding)
        if limit < 1:
            raise ValueError("Search limit must be at least 1.")

        dialect_name = session.get_bind().dialect.name
        embedding_literal = self._embedding_literal(embedding)
        label_params = {
            f"label_{index}": label_key
            for index, label_key in enumerate(normalized_labels)
        }
        label_placeholders = ", ".join(f":{key}" for key in label_params)

        if dialect_name == "postgresql":
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
        elif dialect_name == "oracle":
            sql = text(
                f"""
                SELECT
                    c.id AS chunk_id,
                    d.id AS document_id,
                    d.source AS source,
                    d.title AS title,
                    c.chunk_index AS chunk_index,
                    c.chunk_text AS chunk_text,
                    VECTOR_DISTANCE(
                        c.embedding,
                        TO_VECTOR(:embedding),
                        COSINE
                    ) AS distance
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
                FETCH FIRST :limit ROWS ONLY
                """
            )
        else:
            raise RuntimeError(
                f"Unsupported database dialect for RAG search: {dialect_name}"
            )

        rows = session.execute(
            sql,
            {"embedding": embedding_literal, "limit": limit, **label_params},
        ).mappings()
        return [
            RagSearchResult(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                source=row["source"],
                title=row["title"],
                chunk_index=row["chunk_index"],
                chunk_text=row["chunk_text"],
                distance=float(row["distance"]),
            )
            for row in rows
        ]

    def _get_or_create_label(self, session: Session, label_key: str) -> RagLabel:
        label = session.scalar(select(RagLabel).where(RagLabel.label_key == label_key))
        if label is not None:
            return label

        label = RagLabel(label_key=label_key)
        session.add(label)
        session.flush()
        return label

    def _insert_chunk(
        self,
        session: Session,
        dialect_name: str,
        document_id: int,
        chunk: RagChunkInput,
    ) -> None:
        embedding_literal = self._embedding_literal(chunk.embedding)
        params = {
            "document_id": document_id,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "source_location": chunk.source_location,
            "chunk_text": chunk.chunk_text,
            "metadata_json": self._serialize_json(chunk.metadata),
            "embedding": embedding_literal,
        }

        if dialect_name == "postgresql":
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
        elif dialect_name == "oracle":
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
                    TO_VECTOR(:embedding)
                )
                """
            )
        else:
            raise RuntimeError(
                f"Unsupported database dialect for RAG chunks: {dialect_name}"
            )

        session.execute(sql, params)

    def _validate_chunk(self, chunk: RagChunkInput) -> None:
        if not chunk.chunk_text.strip():
            raise ValueError("RAG chunk text cannot be empty.")
        if chunk.chunk_index < 0:
            raise ValueError("RAG chunk index cannot be negative.")
        self._validate_embedding(chunk.embedding)

    def _validate_embedding(self, embedding: list[float]) -> None:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Embedding must have {EMBEDDING_DIMENSIONS} dimensions; "
                f"received {len(embedding)}."
            )

    def _normalize_labels(self, labels: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for label in labels:
            label_key = label.strip().lower()
            if label_key and label_key not in seen:
                normalized.append(label_key)
                seen.add(label_key)
        return normalized

    def _serialize_json(self, value: dict[str, Any] | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    def _embedding_literal(self, embedding: list[float]) -> str:
        return "[" + ",".join(str(float(value)) for value in embedding) + "]"
