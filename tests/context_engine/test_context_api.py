"""Tests for protected generic Context Engine APIs."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import select

from app.models.context_engine import (
    ContextActionableItemRecord,
    ContextArtifactChunkRecord,
    ContextArtifactRecord,
    ContextEntityRecord,
    ContextIngestionBatchRecord,
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
    assert missing_type.json()["detail"] == (
        "Artifact type 'missing-type' is not registered for domain 'test-domain'."
    )


def batch_payload(*texts: str, artifact_type_id: str = "note") -> dict[str, object]:
    """Return a batch ingestion payload for the fake domain."""
    return {
        "artifacts": [
            {"artifact_type_id": artifact_type_id, "title": text, "text": text}
            for text in texts
        ]
    }


def count_records(db_session, model: type) -> int:
    """Return the number of persisted rows for one ORM model."""
    return int(db_session.scalar(select(sa.func.count()).select_from(model)) or 0)


def test_context_batch_api_ingests_artifacts_in_request_order(
    client, db_session
) -> None:
    headers = access_headers(client, "context-batch")

    response = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers={**headers, "Idempotency-Key": "batch-1"},
        json=batch_payload("First batch note", "Second batch note", "Third"),
    )

    assert response.status_code == 201
    results = response.json()["results"]
    assert [result["artifact"]["text"] for result in results] == [
        "First batch note",
        "Second batch note",
        "Third",
    ]
    for result in results:
        assert result["extractor_ids"] == ["test-domain-extractor"]
        assert [item["item_type"] for item in result["actionable_items"]] == [
            "test_action",
            "test_generated_task",
        ]
        assert result["chunks"][0]["artifact_id"] == result["artifact"]["id"]
    listed = client.get("/api/context/domains/test-domain/artifacts", headers=headers)
    assert [artifact["id"] for artifact in listed.json()["artifacts"]] == [
        result["artifact"]["id"] for result in results
    ]
    assert count_records(db_session, ContextIngestionBatchRecord) == 1


def test_context_batch_api_requires_idempotency_key(client) -> None:
    headers = access_headers(client, "context-batch-key")

    missing = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers=headers,
        json=batch_payload("note"),
    )
    blank = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers={**headers, "Idempotency-Key": "   "},
        json=batch_payload("note"),
    )
    too_long = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers={**headers, "Idempotency-Key": "k" * 256},
        json=batch_payload("note"),
    )

    assert missing.status_code == 400
    assert missing.json()["detail"] == (
        "Idempotency-Key header is required for batch ingestion."
    )
    assert blank.status_code == 400
    assert too_long.status_code == 400
    listed = client.get("/api/context/domains/test-domain/artifacts", headers=headers)
    assert listed.json()["artifacts"] == []


def test_context_batch_api_enforces_batch_size(client) -> None:
    headers = {
        **access_headers(client, "context-batch-size"),
        "Idempotency-Key": "batch-size",
    }

    empty = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers=headers,
        json={"artifacts": []},
    )
    too_many = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers=headers,
        json=batch_payload(*[f"note {index}" for index in range(21)]),
    )
    maximum = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers=headers,
        json=batch_payload(*[f"note {index}" for index in range(20)]),
    )

    assert empty.status_code == 422
    assert too_many.status_code == 422
    assert maximum.status_code == 201
    assert len(maximum.json()["results"]) == 20


def test_context_batch_api_is_atomic_when_one_artifact_fails(
    client, db_session
) -> None:
    headers = access_headers(client, "context-batch-atomic")
    payload = {
        "artifacts": [
            {"artifact_type_id": "note", "text": "Valid note"},
            {"artifact_type_id": "missing-type", "text": "Another valid note"},
        ]
    }

    response = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers={**headers, "Idempotency-Key": "atomic"},
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith("artifacts[1]: Artifact type")
    for model in (
        ContextArtifactRecord,
        ContextArtifactChunkRecord,
        ContextEntityRecord,
        ContextSignalRecord,
        ContextActionableItemRecord,
        ContextSourceLinkRecord,
        ContextIngestionBatchRecord,
    ):
        assert count_records(db_session, model) == 0

    retried = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers={**headers, "Idempotency-Key": "atomic"},
        json=batch_payload("Valid note", "Another valid note"),
    )
    assert retried.status_code == 201


def test_context_batch_api_rejects_missing_domain(client) -> None:
    headers = access_headers(client, "context-batch-domain")

    response = client.post(
        "/api/context/domains/missing-domain/artifact-batches",
        headers={**headers, "Idempotency-Key": "missing-domain"},
        json=batch_payload("note"),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Context domain not found."


def test_context_batch_api_replays_and_conflicts_on_idempotency_key(
    client, db_session
) -> None:
    headers = {
        **access_headers(client, "context-batch-replay"),
        "Idempotency-Key": "replay",
    }
    first = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers=headers,
        json=batch_payload("Replay one", "Replay two"),
    )
    reordered_keys = {
        "artifacts": [
            {"text": text, "metadata": {}, "title": text, "artifact_type_id": "note"}
            for text in ("Replay one", "Replay two")
        ]
    }
    replay = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers=headers,
        json=reordered_keys,
    )
    conflict = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers=headers,
        json=batch_payload("Replay one", "Changed"),
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert count_records(db_session, ContextArtifactRecord) == 2
    assert count_records(db_session, ContextIngestionBatchRecord) == 1


def test_context_idempotency_keys_are_scoped_to_owner(client) -> None:
    owner_headers = access_headers(client, "context-key-owner")
    other_headers = access_headers(client, "context-key-other")

    owner = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers={**owner_headers, "Idempotency-Key": "shared"},
        json=batch_payload("Owner note"),
    )
    other = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers={**other_headers, "Idempotency-Key": "shared"},
        json=batch_payload("Other note"),
    )

    assert owner.status_code == 201
    assert other.status_code == 201
    assert (
        owner.json()["results"][0]["artifact"]["id"]
        != other.json()["results"][0]["artifact"]["id"]
    )


def test_context_artifact_api_supports_optional_idempotency_key(
    client, db_session
) -> None:
    headers = access_headers(client, "context-single-key")
    payload = {"artifact_type_id": "note", "text": "Idempotent single note"}

    without_key = client.post(
        "/api/context/domains/test-domain/artifacts", headers=headers, json=payload
    )
    first = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers={**headers, "Idempotency-Key": "single"},
        json=payload,
    )
    replay = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers={**headers, "Idempotency-Key": "single"},
        json=payload,
    )
    conflict = client.post(
        "/api/context/domains/test-domain/artifacts",
        headers={**headers, "Idempotency-Key": "single"},
        json={**payload, "text": "Different single note"},
    )
    cross_endpoint = client.post(
        "/api/context/domains/test-domain/artifact-batches",
        headers={**headers, "Idempotency-Key": "single"},
        json={"artifacts": [payload]},
    )

    assert without_key.status_code == 201
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert cross_endpoint.status_code == 409
    assert count_records(db_session, ContextArtifactRecord) == 2
    assert count_records(db_session, ContextIngestionBatchRecord) == 1


def test_context_upload_api_supports_optional_idempotency_key(
    client, db_session
) -> None:
    headers = {
        **access_headers(client, "context-upload-key"),
        "Idempotency-Key": "upload",
    }

    def upload(content: bytes):
        return client.post(
            "/api/context/domains/test-domain/artifact-uploads",
            headers=headers,
            data={"artifact_type_id": "note", "metadata_json": '{"a":1,"b":2}'},
            files={"file": ("note.txt", content, "text/plain")},
        )

    first = upload(b"Uploaded idempotent note.")
    replay = upload(b"Uploaded idempotent note.")
    conflict = upload(b"Changed upload content.")

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert count_records(db_session, ContextArtifactRecord) == 1


def test_context_upload_api_preserves_error_handling(client) -> None:
    headers = access_headers(client, "context-upload-errors")

    unsupported = client.post(
        "/api/context/domains/test-domain/artifact-uploads",
        headers=headers,
        data={"artifact_type_id": "note"},
        files={"file": ("image.png", b"\x89PNG", "image/png")},
    )
    bad_metadata = client.post(
        "/api/context/domains/test-domain/artifact-uploads",
        headers=headers,
        data={"artifact_type_id": "note", "metadata_json": "[1]"},
        files={"file": ("note.txt", b"content", "text/plain")},
    )
    missing_domain = client.post(
        "/api/context/domains/missing-domain/artifact-uploads",
        headers=headers,
        data={"artifact_type_id": "note"},
        files={"file": ("note.txt", b"content", "text/plain")},
    )

    assert unsupported.status_code == 400
    assert unsupported.json()["detail"] == (
        "Only text files and extractable PDFs are supported."
    )
    assert bad_metadata.status_code == 400
    assert bad_metadata.json()["detail"] == "metadata_json must be a JSON object."
    assert missing_domain.status_code == 404
