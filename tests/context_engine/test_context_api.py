"""Tests for protected generic Context Engine APIs."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import select

from app.models.context_engine import (
    ContextActionableItemRecord,
    ContextArtifactRecord,
    ContextPerspectiveViewRecord,
    ContextSignalRecord,
    ContextSourceLinkRecord,
)


def create_code(client, code: str, label: str = "messy-notes") -> None:
    """Insert an invitation code through the admin API for test setup."""
    response = client.post(
        "/api/internal/admin/invitations",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"code": code, "label": label},
    )
    assert response.status_code == 201


def access_headers(client, code: str, label: str = "messy-notes") -> dict[str, str]:
    """Redeem a code and return bearer auth headers."""
    create_code(client, code, label)
    redeem = client.post("/api/access/redeem", json={"code": code})
    assert redeem.status_code == 200
    token = redeem.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_context_api_requires_access_token(client) -> None:
    response = client.get("/api/context/domains")

    assert response.status_code == 401
    assert response.json()["detail"] == "Access token required."


def test_context_domain_api_loads_fake_domain_in_test(client) -> None:
    headers = access_headers(client, "context-domain-list")

    response = client.get("/api/context/domains", headers=headers)

    assert response.status_code == 200
    domain_ids = [domain["id"] for domain in response.json()["domains"]]
    assert domain_ids == ["job_search", "test-domain"]

    detail = client.get("/api/context/domains/test-domain", headers=headers)
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["perspectives"] == [{"id": "test-summary"}]
    assert detail_payload["views"] == [
        {
            "id": "test-summary",
            "display_name": "Test Summary",
            "description": "Minimal registered view for tests.",
            "metadata": {},
        }
    ]


def test_context_view_api_builds_owner_scoped_perspective(client) -> None:
    headers = access_headers(client, "context-view")

    created = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers=headers,
        json={
            "artifact_type_id": "note",
            "title": "Perspective note",
            "text": "Perspective content",
        },
    )
    assert created.status_code == 201

    response = client.get(
        "/api/context/domains/test-domain/views/test-summary",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["view"]["view_definition_id"] == "test-summary"
    assert response.json()["view"]["sections"][0]["content"] == "Perspective content"


def test_context_view_api_caches_perspective_until_regenerate(
    client, db_session
) -> None:
    headers = access_headers(client, "context-view-cache")

    first = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers=headers,
        json={
            "artifact_type_id": "note",
            "title": "First note",
            "text": "First cached perspective.",
        },
    )
    assert first.status_code == 201
    generated = client.get(
        "/api/context/domains/test-domain/views/test-summary",
        headers=headers,
    )
    assert generated.status_code == 200
    assert (
        generated.json()["view"]["sections"][0]["content"]
        == "First cached perspective."
    )

    second = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers=headers,
        json={
            "artifact_type_id": "note",
            "title": "Second note",
            "text": "Second source should mark stale.",
        },
    )
    assert second.status_code == 201
    cached = client.get(
        "/api/context/domains/test-domain/views/test-summary",
        headers=headers,
    )
    assert cached.status_code == 200
    cached_view = cached.json()["view"]
    assert cached_view["sections"][0]["content"] == "First cached perspective."
    assert cached_view["metadata"]["is_stale"] is True
    assert cached_view["metadata"]["current_artifact_count"] == 2

    regenerated = client.get(
        "/api/context/domains/test-domain/views/test-summary?regenerate=true",
        headers=headers,
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["view"]["metadata"]["is_stale"] is False
    assert db_session.scalar(select(ContextPerspectiveViewRecord).limit(1)) is not None


def test_context_artifact_api_lists_and_returns_owner_scoped_artifacts(client) -> None:
    owner_headers = access_headers(client, "context-artifact-list")
    other_headers = access_headers(client, "context-artifact-other")

    created = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers=owner_headers,
        json={
            "artifact_type_id": "note",
            "title": "Queryable note",
            "text": "Queryable owner-scoped context.",
        },
    )
    assert created.status_code == 201
    artifact_id = created.json()["artifact"]["id"]

    listed = client.get(
        "/api/context/domains/test-domain/artifacts",
        headers=owner_headers,
    )
    assert listed.status_code == 200
    assert [artifact["id"] for artifact in listed.json()["artifacts"]] == [artifact_id]

    detail = client.get(
        f"/api/context/domains/test-domain/artifacts/{artifact_id}",
        headers=owner_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["artifact"]["title"] == "Queryable note"
    assert detail.json()["chunks"][0]["source_link"]["artifact_id"] == artifact_id

    hidden_detail = client.get(
        f"/api/context/domains/test-domain/artifacts/{artifact_id}",
        headers=other_headers,
    )
    assert hidden_detail.status_code == 404


def test_context_upload_api_extracts_text_file_and_preserves_metadata(client) -> None:
    headers = access_headers(client, "context-upload")

    uploaded = client.post(
        "/api/context/domains/test-domain/artifact-uploads",
        headers=headers,
        data={
            "artifact_type_id": "note",
            "title": "Uploaded note",
            "metadata_json": '{"source":"candidate paste"}',
        },
        files={
            "file": (
                "note.txt",
                b"Uploaded context extraction.",
                "text/plain",
            )
        },
    )

    assert uploaded.status_code == 201
    payload = uploaded.json()
    assert payload["artifact"]["title"] == "Uploaded note"
    assert payload["artifact"]["text"] == "Uploaded context extraction."
    assert payload["artifact"]["metadata"]["ingestion_method"] == "upload"
    assert payload["artifact"]["metadata"]["source"] == "candidate paste"


def test_context_artifact_api_ingests_and_scopes_outputs(client) -> None:
    owner_headers = access_headers(client, "context-owner")
    other_headers = access_headers(client, "context-other")

    created = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers=owner_headers,
        json={
            "artifact_type_id": "note",
            "title": "Owner note",
            "text": "A generic source note for context extraction.",
            "source_uri": "memory://owner-note",
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["artifact"]["domain_id"] == "test-domain"
    assert payload["artifact"]["owner_type"] == "invitation_code"
    assert (
        payload["chunks"][0]["source_link"]["artifact_id"] == payload["artifact"]["id"]
    )
    assert (
        payload["signals"][0]["source_links"][0]["chunk_id"]
        == payload["chunks"][0]["id"]
    )
    assert {item["item_type"] for item in payload["actionable_items"]} == {
        "test_action",
        "test_generated_task",
    }

    owner_signals = client.get(
        "/api/context/domains/test-domain/signals",
        headers=owner_headers,
    )
    assert owner_signals.status_code == 200
    assert len(owner_signals.json()["signals"]) == 1

    owner_tasks = client.get(
        "/api/context/domains/test-domain/tasks",
        headers=owner_headers,
    )
    assert owner_tasks.status_code == 200
    assert len(owner_tasks.json()["tasks"]) == 2

    owner_actionable_items = client.get(
        "/api/context/domains/test-domain/actionable-items",
        headers=owner_headers,
    )
    assert owner_actionable_items.status_code == 200
    assert (
        owner_actionable_items.json()["actionable_items"] == owner_tasks.json()["tasks"]
    )

    other_signals = client.get(
        "/api/context/domains/test-domain/signals",
        headers=other_headers,
    )
    assert other_signals.status_code == 200
    assert other_signals.json()["signals"] == []


def test_context_artifact_api_persists_generic_context_records(
    client, db_session
) -> None:
    headers = access_headers(client, "context-persist")

    created = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers=headers,
        json={
            "artifact_type_id": "note",
            "title": "Persisted note",
            "text": "Persisted context extraction.",
        },
    )

    assert created.status_code == 201
    assert db_session.scalar(select(ContextArtifactRecord).limit(1)) is not None
    assert db_session.scalar(select(ContextSignalRecord).limit(1)) is not None
    assert db_session.scalar(select(ContextActionableItemRecord).limit(1)) is not None
    assert db_session.scalar(select(ContextSourceLinkRecord).limit(1)) is not None


def test_context_persistence_schema_preserves_source_integrity(engine) -> None:
    inspector = sa.inspect(engine)

    chunk_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("context_artifact_chunks")
    }
    source_link_fks = inspector.get_foreign_keys("context_source_links")

    assert "uq_context_artifact_chunks_artifact_index" in chunk_constraints
    assert any(
        fk["referred_table"] == "context_artifacts"
        and fk["constrained_columns"] == ["artifact_id"]
        for fk in source_link_fks
    )


def test_context_artifact_api_rejects_invalid_domain_and_type(client) -> None:
    headers = access_headers(client, "context-invalid")

    missing_domain = client.post(
        "/api/context/domains/missing-domain/artifacts",
        headers=headers,
        json={"artifact_type_id": "note", "text": "content"},
    )
    assert missing_domain.status_code == 404

    missing_type = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers=headers,
        json={"artifact_type_id": "missing-type", "text": "content"},
    )
    assert missing_type.status_code == 400
