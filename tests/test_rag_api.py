"""Tests for protected RAG ingestion and search endpoints."""

from __future__ import annotations

from app.api.routes.rag import get_rag_service
from app.core.config import get_settings
from app.services.rag.local_postgres import LocalPostgresRagStrategy
from app.services.rag.models import EMBEDDING_DIMENSIONS
from app.services.rag.strategy import RagService


class FakeEmbeddingProvider:
    """Deterministic embeddings for endpoint tests."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        embedding = [0.0] * EMBEDDING_DIMENSIONS
        if "beta" in text.lower():
            embedding[1] = 1.0
        else:
            embedding[0] = 1.0
        return embedding


def create_code(client, code: str, label: str = "rag-demo") -> None:
    """Insert an invitation code through the admin API for test setup."""
    response = client.post(
        "/api/internal/admin/invitations",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"code": code, "label": label},
    )
    assert response.status_code == 201


def access_headers(client, code: str, label: str = "rag-demo") -> dict[str, str]:
    """Redeem a code and return bearer auth headers."""
    create_code(client, code, label)
    redeem = client.post("/api/access/redeem", json={"code": code})
    assert redeem.status_code == 200
    token = redeem.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_rag_endpoints_require_access_token(client) -> None:
    response = client.post(
        "/api/rag/search",
        json={"query": "alpha", "labels": ["flow-a"]},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Access token required."


def test_rag_endpoints_reject_messy_notes_experience_token(client) -> None:
    headers = access_headers(client, "rag-messy-token", "messy-notes")

    response = client.post(
        "/api/rag/search",
        headers=headers,
        json={"query": "alpha", "labels": ["flow-a"]},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Access token is not valid for this experience."
    )


def test_ingest_text_and_search_with_label_scope(client) -> None:
    client.app.dependency_overrides[get_rag_service] = lambda: RagService(
        LocalPostgresRagStrategy(embeddings=FakeEmbeddingProvider())
    )
    try:
        headers = access_headers(client, "rag-api")

        alpha = client.post(
            "/api/rag/documents",
            headers=headers,
            data={
                "labels": ["flow-a"],
                "source": "alpha.txt",
                "title": "Alpha",
                "input_text": "alpha renewal policy context",
            },
        )
        assert alpha.status_code == 201
        assert alpha.json()["chunk_count"] == 1
        assert alpha.json()["labels"] == ["flow-a"]

        beta = client.post(
            "/api/rag/documents",
            headers=headers,
            data={
                "labels": ["flow-b"],
                "source": "beta.txt",
                "title": "Beta",
                "input_text": "beta pricing policy context",
            },
        )
        assert beta.status_code == 201

        search = client.post(
            "/api/rag/search",
            headers=headers,
            json={"query": "alpha question", "labels": ["flow-a"], "limit": 5},
        )

        assert search.status_code == 200
        results = search.json()["results"]
        assert len(results) == 1
        assert results[0]["source"] == "alpha.txt"
        assert "beta" not in results[0]["chunk_text"]
    finally:
        client.app.dependency_overrides.pop(get_rag_service, None)


def test_rag_ingest_rejects_missing_content(client) -> None:
    client.app.dependency_overrides[get_rag_service] = lambda: RagService(
        LocalPostgresRagStrategy(embeddings=FakeEmbeddingProvider())
    )
    try:
        headers = access_headers(client, "rag-missing-content")

        response = client.post(
            "/api/rag/documents",
            headers=headers,
            data={"labels": ["flow-a"], "source": "empty"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Provide either input_text or a text/PDF file."
        )
    finally:
        client.app.dependency_overrides.pop(get_rag_service, None)


def test_default_oracle_rag_model_matches_loaded_model() -> None:
    settings = get_settings()

    assert settings.rag_oracle_embedding_model == "MINILM_L12_V2"
