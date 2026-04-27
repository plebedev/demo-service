"""Tests for protected demo run endpoints."""

from __future__ import annotations

from app.db.models import Run


def create_code(client, code: str) -> None:
    """Insert an invitation code through the admin API for test setup."""
    response = client.post(
        "/api/internal/admin/invitations",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"code": code},
    )
    assert response.status_code == 201


def access_headers(client, code: str) -> dict[str, str]:
    """Redeem a code and return bearer auth headers."""
    create_code(client, code)
    redeem = client.post("/api/access/redeem", json={"code": code})
    assert redeem.status_code == 200
    token = redeem.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_run_endpoints_require_access_token(client) -> None:
    response = client.get("/api/runs")
    assert response.status_code == 401
    assert response.json()["detail"] == "Access token required."


def test_create_and_get_run(client, db_session) -> None:
    headers = access_headers(client, "runs-create")

    created = client.post(
        "/api/runs",
        headers=headers,
        json={"title": "Ops intake", "input_text": "line one\nline two"},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "draft"
    assert payload["title"] == "Ops intake"
    assert payload["input_text"] == "line one\nline two"
    assert payload["submitted_at"] is None

    stored = db_session.get(Run, payload["id"])
    assert stored is not None
    assert stored.status == "draft"

    fetched = client.get(f"/api/runs/{payload['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["id"]


def test_list_runs_is_newest_first(client) -> None:
    headers = access_headers(client, "runs-list")

    first = client.post("/api/runs", headers=headers, json={"title": "First"})
    second = client.post("/api/runs", headers=headers, json={"title": "Second"})
    assert first.status_code == 201
    assert second.status_code == 201

    listing = client.get("/api/runs", headers=headers)
    assert listing.status_code == 200
    payload = listing.json()
    assert [run["title"] for run in payload["runs"]] == ["Second", "First"]


def test_update_run_draft(client, db_session) -> None:
    headers = access_headers(client, "runs-update")

    created = client.post("/api/runs", headers=headers, json={"title": "Raw title"})
    run_id = created.json()["id"]

    updated = client.put(
        f"/api/runs/{run_id}",
        headers=headers,
        json={
            "title": "Customer renewal brief",
            "input_text": "Budget pressure\nNeed Oracle-safe rollout",
            "input_metadata_json": {"source_kind": "pasted_text", "note_count": 2},
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["status"] == "draft"
    assert payload["title"] == "Customer renewal brief"
    assert payload["input_metadata_json"]["note_count"] == 2

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.input_text == "Budget pressure\nNeed Oracle-safe rollout"


def test_submit_run_transitions_to_submitted(client, db_session) -> None:
    headers = access_headers(client, "runs-submit")

    created = client.post(
        "/api/runs",
        headers=headers,
        json={"title": "Needs submit", "input_text": "messy notes"},
    )
    run_id = created.json()["id"]

    submitted = client.post(
        f"/api/runs/{run_id}/submit",
        headers=headers,
        json={
            "title": "Submitted brief request",
            "input_text": "messy notes\nfollow-up capped",
            "input_metadata_json": {"source_kind": "pasted_text"},
        },
    )
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["status"] == "submitted"
    assert payload["submitted_at"] is not None

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.status == "submitted"
    assert stored.submitted_at is not None

    conflict = client.post(
        f"/api/runs/{run_id}/submit",
        headers=headers,
        json={},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Only draft or failed runs can be submitted."
