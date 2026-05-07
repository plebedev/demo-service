"""Oracle-native RAG strategy using VECTOR_CHUNKS and VECTOR_EMBEDDING."""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.rag.extraction import combine_sections, extract_sections
from app.services.rag.models import RagDocumentResult, RagSearchResult
from app.services.rag.repository import RagDocumentRepository


class OracleNativeRagStrategy:
    """RAG implementation for Oracle AI Database native vector features."""

    def __init__(self, repository: RagDocumentRepository | None = None) -> None:
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
        """Extract text, then chunk and embed inside Oracle."""
        sections, resolved_source = await extract_sections(
            input_text=input_text,
            file=file,
            fallback_source=source,
        )
        document_text = combine_sections(sections)
        if not document_text:
            raise ValueError("No extractable text was available for RAG ingestion.")

        document = self.repository.create_document(
            session,
            source=resolved_source,
            title=title,
            labels=labels,
        )
        chunk_count = self._insert_oracle_chunks(
            session,
            document_id=document.id,
            document_text=document_text,
            settings=settings,
        )
        session.commit()

        return RagDocumentResult(
            document_id=document.id,
            source=document.source,
            title=document.title,
            labels=[label.label_key for label in document.labels],
            chunk_count=chunk_count,
        )

    def search(
        self,
        session: Session,
        *,
        settings: Settings,
        labels: list[str],
        query: str,
        limit: int,
    ) -> list[RagSearchResult]:
        """Embed the query and search chunks inside Oracle."""
        normalized_labels = self.repository.normalize_labels(labels)
        if not normalized_labels:
            raise ValueError("At least one RAG label is required.")
        if not query.strip():
            raise ValueError("RAG search query cannot be empty.")
        if limit < 1:
            raise ValueError("Search limit must be at least 1.")

        label_params = {
            f"label_{index}": label_key
            for index, label_key in enumerate(normalized_labels)
        }
        label_placeholders = ", ".join(f":{key}" for key in label_params)
        model_name = self.repository.oracle_model_name(
            settings.rag_oracle_embedding_model
        )
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
                    VECTOR_EMBEDDING({model_name} USING :query AS DATA),
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

        rows = session.execute(
            sql,
            {"query": query, "limit": limit, **label_params},
        ).mappings()
        return [self._search_result(row) for row in rows]

    def _insert_oracle_chunks(
        self,
        session: Session,
        *,
        document_id: int,
        document_text: str,
        settings: Settings,
    ) -> int:
        chunk_size = self._oracle_chunk_size(settings.rag_chunk_size)
        chunk_overlap = self._oracle_chunk_overlap(
            settings.rag_chunk_overlap,
            chunk_size,
        )
        model_name = self.repository.oracle_model_name(
            settings.rag_oracle_embedding_model
        )
        sql = text(
            f"""
            INSERT INTO rag_document_chunks (
                document_id,
                chunk_index,
                page_number,
                source_location,
                chunk_text,
                metadata_json,
                embedding
            )
            SELECT
                :document_id,
                ROW_NUMBER() OVER (ORDER BY c.chunk_offset) - 1,
                NULL,
                'offset ' || TO_CHAR(c.chunk_offset),
                c.chunk_text,
                JSON_OBJECT(
                    'chunk_offset' VALUE c.chunk_offset,
                    'chunk_length' VALUE c.chunk_length
                    RETURNING CLOB
                ),
                VECTOR_EMBEDDING({model_name} USING c.chunk_text AS DATA)
            FROM VECTOR_CHUNKS(
                :document_text
                BY CHARACTERS
                MAX {chunk_size}
                OVERLAP {chunk_overlap}
                SPLIT BY RECURSIVELY
                NORMALIZE ALL
            ) c
            """
        )
        session.execute(
            sql,
            {
                "document_id": document_id,
                "document_text": document_text,
            },
        )
        count = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM rag_document_chunks
                WHERE document_id = :document_id
                """
            ),
            {"document_id": document_id},
        ).scalar_one()
        return int(count)

    def _oracle_chunk_size(self, value: int) -> int:
        if value < 50 or value > 4000:
            raise ValueError(
                "Oracle RAG chunk size must be between 50 and 4000 characters."
            )
        return value

    def _oracle_chunk_overlap(self, value: int, chunk_size: int) -> int:
        if value == 0:
            return value
        minimum = max(1, int(chunk_size * 0.05))
        maximum = int(chunk_size * 0.20)
        if value < minimum or value > maximum:
            raise ValueError(
                "Oracle RAG chunk overlap must be 0 or between 5% and 20% "
                "of chunk size."
            )
        return value

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
