"""Tests for Oracle RAG strategy chunking provider selection."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.services.rag.models import ExtractedSection, PreparedRagDocument
from app.services.rag.oracle_native import OracleNativeRagStrategy
from app.services.text_tools import TextToolsChunk


def _prepared_document() -> PreparedRagDocument:
    return PreparedRagDocument(
        source="oracle.txt",
        title=None,
        content_sha256="abc123",
        sections=[
            ExtractedSection(
                text="alpha section text",
                page_number=2,
                source_location="page 2",
            )
        ],
        combined_text="alpha section text",
    )


def test_oracle_strategy_builds_chunks_with_text_tools(monkeypatch) -> None:
    strategy = OracleNativeRagStrategy()
    settings = get_settings().model_copy(
        update={
            "text_tools_enabled": True,
            "text_tools_base_url": "http://text-tools.test",
            "rag_chunk_size": 600,
            "rag_chunk_overlap": 60,
        }
    )
    calls = []

    def fake_chunk_text(self, text: str, *, chunk_size: int, chunk_overlap: int):
        calls.append(
            {
                "base_url": self.base_url,
                "text": text,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            }
        )
        return [
            TextToolsChunk(index=0, text="alpha from rust", bytes=15),
            TextToolsChunk(index=1, text="second rust chunk", bytes=17),
        ]

    monkeypatch.setattr(
        "app.services.text_tools.TextToolsClient.chunk_text",
        fake_chunk_text,
    )

    chunks = strategy._build_text_tools_chunks(_prepared_document(), settings=settings)

    assert [chunk.text for chunk in chunks] == [
        "alpha from rust",
        "second rust chunk",
    ]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert all(chunk.page_number == 2 for chunk in chunks)
    assert calls == [
        {
            "base_url": "http://text-tools.test",
            "text": "alpha section text",
            "chunk_size": 600,
            "chunk_overlap": 60,
        }
    ]


def test_oracle_strategy_requires_text_tools_when_rust_provider_enabled(
    monkeypatch,
) -> None:
    strategy = OracleNativeRagStrategy()
    settings = get_settings().model_copy(
        update={
            "rag_oracle_chunking_provider": "rust",
            "text_tools_enabled": False,
        }
    )

    class FakeSession:
        pass

    with pytest.raises(ValueError, match="TEXT_TOOLS_ENABLED"):
        strategy._insert_chunks(
            FakeSession(),  # type: ignore[arg-type]
            document_id=1,
            prepared=_prepared_document(),
            settings=settings,
        )


def test_oracle_strategy_rejects_unknown_chunking_provider() -> None:
    strategy = OracleNativeRagStrategy()
    settings = get_settings().model_copy(
        update={"rag_oracle_chunking_provider": "surprise"}
    )

    class FakeSession:
        pass

    with pytest.raises(ValueError, match="RAG_ORACLE_CHUNKING_PROVIDER"):
        strategy._insert_chunks(
            FakeSession(),  # type: ignore[arg-type]
            document_id=1,
            prepared=_prepared_document(),
            settings=settings,
        )
