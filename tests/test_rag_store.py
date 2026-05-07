"""Tests for local pgvector RAG persistence."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.services.rag.local_postgres import LocalPostgresRagStrategy
from app.services.rag.models import EMBEDDING_DIMENSIONS


class FakeEmbeddingProvider:
    """Deterministic embeddings for local strategy tests."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, value: str) -> list[float]:
        embedding = [0.0] * EMBEDDING_DIMENSIONS
        if "beta" in value.lower():
            embedding[1] = 1.0
        elif "shared" in value.lower():
            embedding[0] = 0.8
            embedding[1] = 0.2
        else:
            embedding[0] = 1.0
        return embedding


class BadEmbeddingProvider:
    """Embedding provider returning the wrong dimensionality."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 1.0] for _ in texts]


class LengthLimitedEmbeddingProvider(FakeEmbeddingProvider):
    """Embedding provider that rejects oversized inputs like small local models."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        for text_value in texts:
            if len(text_value) > 320:
                raise RuntimeError("the input length exceeds the context length")
        return super().embed(texts)


def test_pgvector_extension_and_rag_tables_are_migrated(db_session) -> None:
    extension = db_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    ).scalar_one()
    assert extension == "vector"

    tables = {
        row[0]
        for row in db_session.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
        )
    }
    assert {
        "rag_documents",
        "rag_labels",
        "rag_document_labels",
        "rag_document_chunks",
    }.issubset(tables)


def test_search_chunks_is_constrained_to_requested_labels(db_session) -> None:
    settings = get_settings()
    strategy = LocalPostgresRagStrategy(embeddings=FakeEmbeddingProvider())

    alpha = asyncio.run(
        strategy.ingest_document(
            db_session,
            settings=settings,
            source="alpha.txt",
            title="Alpha",
            labels=["Flow-A"],
            input_text="alpha relevant chunk",
            file=None,
        )
    )
    beta = asyncio.run(
        strategy.ingest_document(
            db_session,
            settings=settings,
            source="beta.txt",
            title="Beta",
            labels=["Flow-B"],
            input_text="beta should not leak into flow a",
            file=None,
        )
    )
    shared = asyncio.run(
        strategy.ingest_document(
            db_session,
            settings=settings,
            source="shared.txt",
            title="Shared",
            labels=["Flow-A", "Flow-C"],
            input_text="shared flow a context",
            file=None,
        )
    )

    results = strategy.search(
        db_session,
        settings=settings,
        labels=["flow-a"],
        query="alpha question",
        limit=10,
    )

    document_ids = {result.document_id for result in results}
    assert alpha.document_id in document_ids
    assert shared.document_id in document_ids
    assert beta.document_id not in document_ids
    assert all("beta" not in result.chunk_text for result in results)


def test_local_strategy_rejects_wrong_embedding_dimensions(db_session) -> None:
    strategy = LocalPostgresRagStrategy(embeddings=BadEmbeddingProvider())

    with pytest.raises(ValueError, match="384 dimensions"):
        asyncio.run(
            strategy.ingest_document(
                db_session,
                settings=get_settings(),
                source="bad.txt",
                title=None,
                labels=["flow-a"],
                input_text="bad vector",
                file=None,
            )
        )


def test_local_strategy_splits_embedding_chunks_that_exceed_context(
    db_session,
) -> None:
    strategy = LocalPostgresRagStrategy(embeddings=LengthLimitedEmbeddingProvider())
    settings = get_settings().model_copy(
        update={"rag_chunk_size": 600, "rag_chunk_overlap": 60}
    )

    result = asyncio.run(
        strategy.ingest_document(
            db_session,
            settings=settings,
            source="long-url.txt",
            title=None,
            labels=["flow-a"],
            input_text=("https://example.test/" + ("alpha" * 140)),
            file=None,
        )
    )

    assert result.chunk_count > 1
