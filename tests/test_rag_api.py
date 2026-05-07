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

    personas = client.get("/api/rag/personas", headers=headers)
    assert personas.status_code == 403
    assert personas.json()["detail"] == (
        "Access token is not valid for this experience."
    )


def test_rag_persona_crud_is_scoped_to_invitation_code(client) -> None:
    headers = access_headers(client, "rag-persona-a")

    created = client.post(
        "/api/rag/personas",
        headers=headers,
        json={
            "name": "Renewals Assistant",
            "instructions": "Answer renewal questions from uploaded playbooks.",
            "capabilities": "Renewal policy lookup",
        },
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["name"] == "Renewals Assistant"
    assert created_payload["instructions"] == (
        "Answer renewal questions from uploaded playbooks."
    )
    assert created_payload["capabilities"] == "Renewal policy lookup"
    persona_id = created_payload["id"]

    listing = client.get("/api/rag/personas", headers=headers)
    assert listing.status_code == 200
    assert [persona["id"] for persona in listing.json()["personas"]] == [persona_id]

    fetched = client.get(f"/api/rag/personas/{persona_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == persona_id

    updated = client.put(
        f"/api/rag/personas/{persona_id}",
        headers=headers,
        json={
            "name": "Renewals Specialist",
            "instructions": "Answer only from renewal and escalation documents.",
            "capabilities": "Renewals and escalations",
            "tool_config": "[]",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renewals Specialist"
    assert updated.json()["tool_config"] == "[]"

    deleted = client.delete(f"/api/rag/personas/{persona_id}", headers=headers)
    assert deleted.status_code == 204

    missing = client.get(f"/api/rag/personas/{persona_id}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Persona not found."


def test_rag_persona_duplicate_names_are_rejected_within_invitation(
    client,
) -> None:
    headers = access_headers(client, "rag-persona-duplicate")
    payload = {
        "name": "Policy Helper",
        "instructions": "Answer from uploaded policy documents.",
    }

    first = client.post("/api/rag/personas", headers=headers, json=payload)
    assert first.status_code == 201

    duplicate = client.post(
        "/api/rag/personas",
        headers=headers,
        json={**payload, "name": "  policy   helper  "},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == (
        "An active persona with this name already exists."
    )


def test_rag_persona_name_can_repeat_across_invitation_codes(client) -> None:
    first_headers = access_headers(client, "rag-persona-tenant-a")
    second_headers = access_headers(client, "rag-persona-tenant-b")
    payload = {
        "name": "Policy Helper",
        "instructions": "Answer from uploaded policy documents.",
    }

    first = client.post("/api/rag/personas", headers=first_headers, json=payload)
    second = client.post("/api/rag/personas", headers=second_headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_rag_persona_cross_invitation_access_does_not_leak(client) -> None:
    owner_headers = access_headers(client, "rag-persona-owner")
    other_headers = access_headers(client, "rag-persona-other")

    created = client.post(
        "/api/rag/personas",
        headers=owner_headers,
        json={
            "name": "Private Helper",
            "instructions": "Answer from private uploaded documents.",
        },
    )
    assert created.status_code == 201
    persona_id = created.json()["id"]

    listing = client.get("/api/rag/personas", headers=other_headers)
    assert listing.status_code == 200
    assert listing.json()["personas"] == []

    fetched = client.get(f"/api/rag/personas/{persona_id}", headers=other_headers)
    assert fetched.status_code == 404
    assert fetched.json()["detail"] == "Persona not found."

    updated = client.put(
        f"/api/rag/personas/{persona_id}",
        headers=other_headers,
        json={
            "name": "Changed",
            "instructions": "Try to cross tenant boundaries.",
        },
    )
    assert updated.status_code == 404
    assert updated.json()["detail"] == "Persona not found."

    deleted = client.delete(f"/api/rag/personas/{persona_id}", headers=other_headers)
    assert deleted.status_code == 404
    assert deleted.json()["detail"] == "Persona not found."

    owner_fetch = client.get(f"/api/rag/personas/{persona_id}", headers=owner_headers)
    assert owner_fetch.status_code == 200
    assert owner_fetch.json()["name"] == "Private Helper"


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
