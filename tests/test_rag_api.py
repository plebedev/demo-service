"""Tests for protected RAG ingestion and search endpoints."""

from __future__ import annotations

from app.api.routes.rag import get_rag_service
from app.core.config import get_settings
from app.models.rag import RagDocument, RagDocumentChunk, RagPersonaDocument
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


def create_persona(client, headers: dict[str, str], name: str = "Policy Helper") -> int:
    """Create a RAG persona and return its id."""
    response = client.post(
        "/api/rag/personas",
        headers=headers,
        json={
            "name": name,
            "instructions": "Answer from uploaded policy documents.",
            "capabilities": "Policy lookup",
        },
    )
    assert response.status_code == 201
    return int(response.json()["id"])


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

    documents = client.get("/api/rag/personas/1/documents", headers=headers)
    assert documents.status_code == 403
    assert documents.json()["detail"] == (
        "Access token is not valid for this experience."
    )

    conversations = client.get("/api/rag/conversations", headers=headers)
    assert conversations.status_code == 403
    assert conversations.json()["detail"] == (
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


def test_rag_conversations_are_scoped_to_invitation_code(client) -> None:
    owner_headers = access_headers(client, "rag-conversation-owner")
    other_headers = access_headers(client, "rag-conversation-other")
    persona_id = create_persona(client, owner_headers, "Policy Helper")

    created = client.post(
        "/api/rag/conversations",
        headers=owner_headers,
        json={"persona_id": persona_id, "title": "Policy chat"},
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["persona_id"] == persona_id
    assert created_payload["persona_name"] == "Policy Helper"
    assert created_payload["title"] == "Policy chat"
    conversation_id = created_payload["id"]

    owner_list = client.get("/api/rag/conversations", headers=owner_headers)
    assert owner_list.status_code == 200
    assert [item["id"] for item in owner_list.json()["conversations"]] == [
        conversation_id
    ]

    detail = client.get(
        f"/api/rag/conversations/{conversation_id}",
        headers=owner_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["conversation"]["id"] == conversation_id
    assert detail.json()["messages"] == []

    other_list = client.get("/api/rag/conversations", headers=other_headers)
    assert other_list.status_code == 200
    assert other_list.json()["conversations"] == []

    other_detail = client.get(
        f"/api/rag/conversations/{conversation_id}",
        headers=other_headers,
    )
    assert other_detail.status_code == 404
    assert other_detail.json()["detail"] == "Conversation not found."

    cross_persona_create = client.post(
        "/api/rag/conversations",
        headers=other_headers,
        json={"persona_id": persona_id, "title": "Cross tenant attempt"},
    )
    assert cross_persona_create.status_code == 404
    assert cross_persona_create.json()["detail"] == "Persona not found."


def test_rag_persona_documents_are_scoped_and_reused(
    client,
    db_session,
) -> None:
    client.app.dependency_overrides[get_rag_service] = lambda: RagService(
        LocalPostgresRagStrategy(embeddings=FakeEmbeddingProvider())
    )
    try:
        owner_headers = access_headers(client, "rag-doc-owner")
        other_headers = access_headers(client, "rag-doc-other")
        first_persona_id = create_persona(client, owner_headers, "Policy Helper")
        second_persona_id = create_persona(client, owner_headers, "Renewal Helper")

        first_upload = client.post(
            f"/api/rag/personas/{first_persona_id}/documents",
            headers=owner_headers,
            data={
                "source": "policy.txt",
                "title": "Policy",
                "input_text": "alpha renewal policy context",
            },
        )
        assert first_upload.status_code == 201
        first_payload = first_upload.json()
        assert first_payload["reused_existing_document"] is False
        document_id = first_payload["document"]["document_id"]
        assert first_payload["document"]["chunk_count"] == 1

        repeated_upload = client.post(
            f"/api/rag/personas/{first_persona_id}/documents",
            headers=owner_headers,
            data={
                "source": "policy-renamed.txt",
                "title": "Policy Renamed",
                "input_text": "alpha renewal policy context",
            },
        )
        assert repeated_upload.status_code == 201
        repeated_payload = repeated_upload.json()
        assert repeated_payload["reused_existing_document"] is True
        assert repeated_payload["document"]["document_id"] == document_id

        second_upload = client.post(
            f"/api/rag/personas/{second_persona_id}/documents",
            headers=owner_headers,
            data={
                "source": "policy-copy.txt",
                "title": "Policy Copy",
                "input_text": "alpha renewal policy context",
            },
        )
        assert second_upload.status_code == 201
        assert second_upload.json()["reused_existing_document"] is True
        assert second_upload.json()["document"]["document_id"] == document_id

        owner_list = client.get(
            f"/api/rag/personas/{first_persona_id}/documents",
            headers=owner_headers,
        )
        assert owner_list.status_code == 200
        assert [item["document_id"] for item in owner_list.json()["documents"]] == [
            document_id
        ]

        other_list = client.get(
            f"/api/rag/personas/{first_persona_id}/documents",
            headers=other_headers,
        )
        assert other_list.status_code == 404
        assert other_list.json()["detail"] == "Persona not found."

        other_unlink = client.delete(
            f"/api/rag/personas/{first_persona_id}/documents/{document_id}",
            headers=other_headers,
        )
        assert other_unlink.status_code == 404
        assert other_unlink.json()["detail"] == "Persona not found."

        assert db_session.query(RagDocument).count() == 1
        assert db_session.query(RagDocumentChunk).count() == 1
        assert db_session.query(RagPersonaDocument).count() == 2

        unlink = client.delete(
            f"/api/rag/personas/{first_persona_id}/documents/{document_id}",
            headers=owner_headers,
        )
        assert unlink.status_code == 204

        db_session.expire_all()
        assert db_session.query(RagDocument).count() == 1
        assert db_session.query(RagDocumentChunk).count() == 1
        assert db_session.query(RagPersonaDocument).count() == 1

        remaining = client.get(
            f"/api/rag/personas/{second_persona_id}/documents",
            headers=owner_headers,
        )
        assert remaining.status_code == 200
        assert [item["document_id"] for item in remaining.json()["documents"]] == [
            document_id
        ]
    finally:
        client.app.dependency_overrides.pop(get_rag_service, None)


def test_rag_persona_document_upload_requires_existing_persona(client) -> None:
    client.app.dependency_overrides[get_rag_service] = lambda: RagService(
        LocalPostgresRagStrategy(embeddings=FakeEmbeddingProvider())
    )
    try:
        headers = access_headers(client, "rag-doc-missing-persona")

        upload = client.post(
            "/api/rag/personas/999/documents",
            headers=headers,
            data={
                "source": "policy.txt",
                "input_text": "alpha renewal policy context",
            },
        )

        assert upload.status_code == 404
        assert upload.json()["detail"] == "Persona not found."
    finally:
        client.app.dependency_overrides.pop(get_rag_service, None)


def test_persona_document_search_is_limited_to_linked_documents(
    client,
    db_session,
) -> None:
    service = RagService(LocalPostgresRagStrategy(embeddings=FakeEmbeddingProvider()))
    client.app.dependency_overrides[get_rag_service] = lambda: service
    try:
        headers = access_headers(client, "rag-persona-search")
        policy_persona_id = create_persona(client, headers, "Policy Helper")
        pricing_persona_id = create_persona(client, headers, "Pricing Helper")

        policy_upload = client.post(
            f"/api/rag/personas/{policy_persona_id}/documents",
            headers=headers,
            data={
                "source": "policy.txt",
                "title": "Policy",
                "input_text": "alpha renewal policy context",
            },
        )
        assert policy_upload.status_code == 201

        pricing_upload = client.post(
            f"/api/rag/personas/{pricing_persona_id}/documents",
            headers=headers,
            data={
                "source": "pricing.txt",
                "title": "Pricing",
                "input_text": "beta pricing policy context",
            },
        )
        assert pricing_upload.status_code == 201

        policy_results = service.search_persona_documents(
            db_session,
            settings=get_settings(),
            persona_id=policy_persona_id,
            query="beta pricing question",
            limit=5,
        )
        assert [result.source for result in policy_results] == ["policy.txt"]
        assert all("beta" not in result.chunk_text for result in policy_results)

        pricing_results = service.search_persona_documents(
            db_session,
            settings=get_settings(),
            persona_id=pricing_persona_id,
            query="beta pricing question",
            limit=5,
        )
        assert [result.source for result in pricing_results] == ["pricing.txt"]
        assert all("beta" in result.chunk_text for result in pricing_results)
    finally:
        client.app.dependency_overrides.pop(get_rag_service, None)


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
