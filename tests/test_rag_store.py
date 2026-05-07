"""Tests for label-scoped RAG document persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.rag_store import EMBEDDING_DIMENSIONS, RagChunkInput, RagStore


def embedding(first: float, second: float = 0.0) -> list[float]:
    """Build a fixed-size test embedding."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[0] = first
    values[1] = second
    return values


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
    store = RagStore()

    alpha_document = store.create_document(
        db_session,
        source="alpha.txt",
        title="Alpha",
        labels=["Flow-A"],
        chunks=[
            RagChunkInput(
                chunk_text="alpha relevant chunk",
                embedding=embedding(1.0),
                chunk_index=0,
            )
        ],
    )
    beta_document = store.create_document(
        db_session,
        source="beta.txt",
        title="Beta",
        labels=["Flow-B"],
        chunks=[
            RagChunkInput(
                chunk_text="beta should not leak into flow a",
                embedding=embedding(1.0),
                chunk_index=0,
            )
        ],
    )
    shared_document = store.create_document(
        db_session,
        source="shared.txt",
        title="Shared",
        labels=["Flow-A", "Flow-C"],
        chunks=[
            RagChunkInput(
                chunk_text="shared flow a context",
                embedding=embedding(0.8, 0.2),
                chunk_index=0,
            )
        ],
    )
    db_session.commit()

    results = store.search_chunks(
        db_session,
        labels=["flow-a"],
        embedding=embedding(1.0),
        limit=10,
    )

    document_ids = {result.document_id for result in results}
    assert alpha_document.id in document_ids
    assert shared_document.id in document_ids
    assert beta_document.id not in document_ids
    assert all("beta" not in result.chunk_text for result in results)


def test_store_rejects_wrong_embedding_dimensions(db_session) -> None:
    store = RagStore()

    with pytest.raises(ValueError, match="384 dimensions"):
        store.create_document(
            db_session,
            source="bad.txt",
            labels=["flow-a"],
            chunks=[
                RagChunkInput(
                    chunk_text="bad vector",
                    embedding=[0.0, 1.0],
                    chunk_index=0,
                )
            ],
        )

    with pytest.raises(ValueError, match="384 dimensions"):
        store.search_chunks(
            db_session,
            labels=["flow-a"],
            embedding=[0.0, 1.0],
        )
