"""Tests for protected generic Context Engine APIs."""

from __future__ import annotations


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
    assert response.json()["domains"] == [
        {
            "id": "test-domain",
            "display_name": "Test Domain",
            "metadata": {"purpose": "architecture-validation"},
        }
    ]


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

    other_signals = client.get(
        "/api/context/domains/test-domain/signals",
        headers=other_headers,
    )
    assert other_signals.status_code == 200
    assert other_signals.json()["signals"] == []


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
