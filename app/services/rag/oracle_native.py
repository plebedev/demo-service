"""Oracle-native RAG strategy using VECTOR_CHUNKS and VECTOR_EMBEDDING."""

from __future__ import annotations

import logging
from typing import Any

import oracledb
from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.services.rag.models import (
    PreparedRagChunk,
    PreparedRagDocument,
    RagDocumentResult,
    RagSearchResult,
)
from app.services.rag.repository import RagDocumentRepository
from app.services.text_tools import TextToolsClient

logger = logging.getLogger(__name__)


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
        """Chunk and embed an already extracted document inside Oracle."""
        document = self.repository.create_document(
            session,
            source=prepared.source,
            title=prepared.title,
            labels=labels,
            content_sha256=prepared.content_sha256,
        )
        chunk_count = self._insert_chunks(
            session,
            document_id=document.id,
            prepared=prepared,
            settings=settings,
        )
        log_event(
            logger,
            "oracle_rag_chunks_inserted",
            chunking_provider=settings.rag_oracle_chunking_provider,
            document_id=document.id,
            chunk_count=chunk_count,
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
        if persona_id < 1:
            raise ValueError("RAG persona id must be positive.")
        if not query.strip():
            raise ValueError("RAG search query cannot be empty.")
        if limit < 1:
            raise ValueError("Search limit must be at least 1.")

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
            JOIN rag_persona_documents pd ON pd.document_id = d.id
            WHERE pd.persona_id = :persona_id
            ORDER BY distance ASC
            FETCH FIRST :limit ROWS ONLY
            """
        )
        rows = session.execute(
            sql,
            {"query": query, "persona_id": persona_id, "limit": limit},
        ).mappings()
        return [self._search_result(row) for row in rows]

    def _insert_chunks(
        self,
        session: Session,
        *,
        document_id: int,
        prepared: PreparedRagDocument,
        settings: Settings,
    ) -> int:
        provider = settings.rag_oracle_chunking_provider.strip().lower()
        if provider == "oracle":
            return self._insert_oracle_chunks(
                session,
                document_id=document_id,
                document_text=prepared.combined_text,
                settings=settings,
            )
        if provider == "rust":
            if not settings.text_tools_enabled:
                raise ValueError(
                    "TEXT_TOOLS_ENABLED must be true when "
                    "RAG_ORACLE_CHUNKING_PROVIDER=rust."
                )
            prepared_chunks = self._build_text_tools_chunks(
                prepared,
                settings=settings,
            )
            log_event(
                logger,
                "oracle_rag_text_tools_chunking_succeeded",
                section_count=len(prepared.sections),
                chunk_count=len(prepared_chunks),
                text_tools_base_url=settings.text_tools_base_url,
            )
            return self._insert_prepared_chunks(
                session,
                document_id=document_id,
                prepared_chunks=prepared_chunks,
                settings=settings,
            )
        raise ValueError("RAG_ORACLE_CHUNKING_PROVIDER must be 'oracle' or 'rust'.")

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
        raw_conn = session.connection().connection.driver_connection
        if raw_conn is None:
            raise RuntimeError("Expected an oracledb connection but got None")
        clob = raw_conn.createlob(oracledb.DB_TYPE_CLOB)
        clob.write(document_text)
        session.execute(
            sql,
            {
                "document_id": document_id,
                "document_text": clob,
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

    def _build_text_tools_chunks(
        self,
        prepared: PreparedRagDocument,
        *,
        settings: Settings,
    ) -> list[PreparedRagChunk]:
        client = TextToolsClient(settings)
        chunks: list[PreparedRagChunk] = []
        for section in prepared.sections:
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
        if not chunks:
            raise ValueError("No extractable text was available for RAG ingestion.")
        return chunks

    def _insert_prepared_chunks(
        self,
        session: Session,
        *,
        document_id: int,
        prepared_chunks: list[PreparedRagChunk],
        settings: Settings,
    ) -> int:
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
            VALUES (
                :document_id,
                :chunk_index,
                :page_number,
                :source_location,
                :chunk_text,
                JSON_OBJECT(
                    'chunk_provider' VALUE 'rust',
                    'chunk_length' VALUE :chunk_length
                    RETURNING CLOB
                ),
                VECTOR_EMBEDDING({model_name} USING :chunk_text AS DATA)
            )
            """
        )
        for chunk in prepared_chunks:
            session.execute(
                sql,
                {
                    "document_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "source_location": chunk.source_location,
                    "chunk_text": chunk.text,
                    "chunk_length": len(chunk.text),
                },
            )
        return len(prepared_chunks)

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
