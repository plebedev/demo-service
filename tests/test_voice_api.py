"""Tests for the voice experience API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.voice import VoiceExperienceConfig, VoicePersona


# ---------------------------------------------------------------------------
# Helpers — same pattern as test_rag_api.py
# ---------------------------------------------------------------------------


def _create_code(client: TestClient, code: str, label: str = "voice-demo") -> None:
    """Insert an invitation code via the admin API."""
    response = client.post(
        "/api/internal/admin/invitations",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"code": code, "label": label},
    )
    assert response.status_code == 201


def voice_access_headers(
    client: TestClient, code: str = "voice-code"
) -> dict[str, str]:
    """Redeem a voice-demo invitation code and return Bearer auth headers."""
    _create_code(client, code, "voice-demo")
    redeem = client.post("/api/access/redeem", json={"code": code})
    assert redeem.status_code == 200
    token = redeem.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_voice_config(
    client: TestClient,
    headers: dict[str, str],
    voice_name: str = "eve",
    voice_provider: str | None = None,
) -> dict:  # type: ignore[type-arg]
    """Create or update the voice experience config and return the response body."""
    response = client.put(
        "/api/voice/config",
        headers=headers,
        json={"voice_name": voice_name, "voice_provider": voice_provider},
    )
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def create_voice_persona(
    client: TestClient,
    headers: dict[str, str],
    name: str = "Employer Advisor",
    instructions: str = "You are a workforce development advisor.",
    capabilities: str | None = "Helps employers assess workforce readiness.",
    tool_config: str | None = None,
) -> int:
    """Create a voice persona and return its id."""
    response = client.post(
        "/api/voice/personas",
        headers=headers,
        json={
            "name": name,
            "instructions": instructions,
            "capabilities": capabilities,
            "tool_config": tool_config,
        },
    )
    assert response.status_code == 201
    return int(response.json()["id"])


# ---------------------------------------------------------------------------
# Auth & scope
# ---------------------------------------------------------------------------


def test_voice_config_requires_access_token(client: TestClient) -> None:
    """GET /api/voice/config rejects requests with no bearer token."""
    response = client.get("/api/voice/config")
    assert response.status_code == 401
    assert response.json()["detail"] == "Access token required."


def test_voice_config_rejects_wrong_experience_token(client: TestClient) -> None:
    """Voice endpoints reject tokens scoped to a different experience."""
    _create_code(client, "messy-notes-code", "messy-notes")
    redeem = client.post("/api/access/redeem", json={"code": "messy-notes-code"})
    assert redeem.status_code == 200
    wrong_headers = {"Authorization": f"Bearer {redeem.json()['access_token']}"}

    response = client.get("/api/voice/config", headers=wrong_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Access token is not valid for this experience."


def test_voice_personas_requires_access_token(client: TestClient) -> None:
    """GET /api/voice/personas rejects requests with no bearer token."""
    response = client.get("/api/voice/personas")
    assert response.status_code == 401


def test_admin_voice_routes_require_admin_secret(client: TestClient) -> None:
    """Admin voice routes reject requests with no admin secret."""
    response = client.get("/api/internal/admin/voice/experiences/voice-demo/config")
    assert response.status_code == 401


def test_admin_voice_routes_accept_admin_secret(client: TestClient) -> None:
    """Admin voice routes accept requests with the correct admin secret."""
    response = client.get(
        "/api/internal/admin/voice/experiences/voice-demo/config",
        headers={"X-Admin-Secret": "test-admin-secret"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------


def test_voice_config_returns_404_when_not_initialized(client: TestClient) -> None:
    """GET /api/voice/config returns 404 before any config has been saved."""
    headers = voice_access_headers(client, "config-404-code")
    response = client.get("/api/voice/config", headers=headers)
    assert response.status_code == 404


def test_voice_config_put_creates_config(client: TestClient) -> None:
    """PUT /api/voice/config creates a config and returns the created record."""
    headers = voice_access_headers(client, "config-create-code")
    payload = create_voice_config(client, headers, voice_name="eve", voice_provider="xai")

    assert payload["voice_name"] == "eve"
    assert payload["voice_provider"] == "xai"
    assert payload["experience_id"] == "voice-demo"
    assert payload["id"] is not None
    assert payload["created_at"] is not None
    assert payload["updated_at"] is not None


def test_voice_config_put_updates_existing_config(client: TestClient) -> None:
    """PUT /api/voice/config updates voice fields when config already exists."""
    headers = voice_access_headers(client, "config-update-code")
    create_voice_config(client, headers, voice_name="eve", voice_provider="xai")

    response = client.put(
        "/api/voice/config",
        headers=headers,
        json={"voice_name": "alloy", "voice_provider": "openai"},
    )
    assert response.status_code == 200
    assert response.json()["voice_name"] == "alloy"
    assert response.json()["voice_provider"] == "openai"


def test_voice_config_get_returns_saved_config(client: TestClient) -> None:
    """GET /api/voice/config returns the saved config."""
    headers = voice_access_headers(client, "config-get-code")
    create_voice_config(client, headers, voice_name="eve")

    response = client.get("/api/voice/config", headers=headers)
    assert response.status_code == 200
    assert response.json()["voice_name"] == "eve"


def test_voice_config_stored_with_correct_experience_id(
    client: TestClient, db_session: Session
) -> None:
    """Config is stored in the DB with experience_id='voice-demo'."""
    headers = voice_access_headers(client, "config-db-code")
    create_voice_config(client, headers, voice_name="eve")

    record = (
        db_session.query(VoiceExperienceConfig)
        .filter(VoiceExperienceConfig.experience_id == "voice-demo")
        .first()
    )
    assert record is not None
    assert record.voice_name == "eve"


def test_list_voice_providers_returns_all_providers(client: TestClient) -> None:
    """GET /api/voice/providers returns xAI and OpenAI with their voice lists."""
    headers = voice_access_headers(client, "providers-list-code")
    response = client.get("/api/voice/providers", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert "providers" in data
    provider_ids = {p["provider_id"] for p in data["providers"]}
    assert provider_ids == {"xai", "openai"}

    xai = next(p for p in data["providers"] if p["provider_id"] == "xai")
    assert xai["provider_name"] == "xAI"
    assert set(xai["voices"]) == {"eve", "ara", "rex", "sal", "leo"}

    openai = next(p for p in data["providers"] if p["provider_id"] == "openai")
    assert openai["provider_name"] == "OpenAI"
    assert set(openai["voices"]) == {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


# ---------------------------------------------------------------------------
# Persona CRUD
# ---------------------------------------------------------------------------


def test_voice_personas_returns_empty_list_initially(client: TestClient) -> None:
    """GET /api/voice/personas returns an empty list when no personas exist."""
    headers = voice_access_headers(client, "personas-empty-code")
    response = client.get("/api/voice/personas", headers=headers)
    assert response.status_code == 200
    assert response.json()["personas"] == []


def test_voice_persona_create_returns_201(client: TestClient) -> None:
    """POST /api/voice/personas creates a persona and returns 201."""
    headers = voice_access_headers(client, "persona-create-code")
    response = client.post(
        "/api/voice/personas",
        headers=headers,
        json={
            "name": "Employer Advisor",
            "instructions": "You are a workforce advisor.",
            "capabilities": "Workforce readiness assessment.",
            "tool_config": None,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Employer Advisor"
    assert payload["instructions"] == "You are a workforce advisor."
    assert payload["capabilities"] == "Workforce readiness assessment."
    assert payload["tool_config"] is None
    assert payload["is_active"] is True
    assert payload["experience_id"] == "voice-demo"


def test_voice_persona_created_persona_appears_in_list(client: TestClient) -> None:
    """A created persona is returned in GET /api/voice/personas."""
    headers = voice_access_headers(client, "persona-list-code")
    persona_id = create_voice_persona(client, headers, name="Test Persona")

    response = client.get("/api/voice/personas", headers=headers)
    assert response.status_code == 200
    ids = [p["id"] for p in response.json()["personas"]]
    assert persona_id in ids


def test_voice_persona_duplicate_name_returns_409(client: TestClient) -> None:
    """Creating a persona with a duplicate normalized name returns 409."""
    headers = voice_access_headers(client, "persona-dup-code")
    create_voice_persona(client, headers, name="Duplicate Advisor")

    response = client.post(
        "/api/voice/personas",
        headers=headers,
        json={"name": "Duplicate Advisor", "instructions": "Another one."},
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_voice_persona_name_normalization_detects_duplicate(client: TestClient) -> None:
    """Duplicate detection is case-insensitive and whitespace-normalized."""
    headers = voice_access_headers(client, "persona-norm-code")
    create_voice_persona(client, headers, name="Employer Advisor")

    response = client.post(
        "/api/voice/personas",
        headers=headers,
        json={"name": "  employer  advisor  ", "instructions": "Same name."},
    )
    assert response.status_code == 409


def test_voice_persona_name_key_stored_normalized(
    client: TestClient, db_session: Session
) -> None:
    """The name_key column stores the normalized (lowercased, collapsed) name."""
    headers = voice_access_headers(client, "persona-namekey-code")
    persona_id = create_voice_persona(client, headers, name="  Employer  Advisor  ")

    record = db_session.get(VoicePersona, persona_id)
    assert record is not None
    assert record.name_key == "employer advisor"


def test_voice_persona_patch_updates_instructions(client: TestClient) -> None:
    """PATCH /api/voice/personas/{id} updates instructions."""
    headers = voice_access_headers(client, "persona-patch-code")
    persona_id = create_voice_persona(client, headers, name="Patch Advisor")

    response = client.patch(
        f"/api/voice/personas/{persona_id}",
        headers=headers,
        json={"instructions": "Updated instructions."},
    )
    assert response.status_code == 200
    assert response.json()["instructions"] == "Updated instructions."


def test_voice_persona_patch_is_partial(client: TestClient) -> None:
    """PATCH only modifies provided fields; others are unchanged."""
    headers = voice_access_headers(client, "persona-partial-code")
    persona_id = create_voice_persona(
        client,
        headers,
        name="Partial Advisor",
        capabilities="Original capabilities.",
    )

    client.patch(
        f"/api/voice/personas/{persona_id}",
        headers=headers,
        json={"instructions": "New instructions."},
    )

    response = client.get("/api/voice/personas", headers=headers)
    updated = next(p for p in response.json()["personas"] if p["id"] == persona_id)
    assert updated["capabilities"] == "Original capabilities."
    assert updated["instructions"] == "New instructions."


def test_voice_persona_patch_returns_404_for_missing_id(client: TestClient) -> None:
    """PATCH on a non-existent persona returns 404."""
    headers = voice_access_headers(client, "persona-404-patch-code")
    response = client.patch(
        "/api/voice/personas/99999",
        headers=headers,
        json={"instructions": "Doesn't matter."},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Persona not found."


def test_voice_persona_deactivate_soft_deletes(
    client: TestClient, db_session: Session
) -> None:
    """POST .../deactivate sets is_active=False in the database."""
    headers = voice_access_headers(client, "persona-deactivate-code")
    persona_id = create_voice_persona(client, headers, name="Deactivate Me")

    response = client.post(
        f"/api/voice/personas/{persona_id}/deactivate",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    db_session.expire_all()
    record = db_session.get(VoicePersona, persona_id)
    assert record is not None
    assert record.is_active is False


def test_voice_persona_deactivated_excluded_from_list(client: TestClient) -> None:
    """Deactivated personas are absent from GET /api/voice/personas."""
    headers = voice_access_headers(client, "persona-excl-code")
    persona_id = create_voice_persona(client, headers, name="To Be Removed")

    client.post(f"/api/voice/personas/{persona_id}/deactivate", headers=headers)

    response = client.get("/api/voice/personas", headers=headers)
    ids = [p["id"] for p in response.json()["personas"]]
    assert persona_id not in ids


def test_voice_persona_deactivate_returns_404_for_missing_id(
    client: TestClient,
) -> None:
    """POST .../deactivate on a non-existent persona returns 404."""
    headers = voice_access_headers(client, "persona-deactivate-404-code")
    response = client.post("/api/voice/personas/99999/deactivate", headers=headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cross-experience isolation
# ---------------------------------------------------------------------------


def test_rag_demo_token_cannot_access_voice_personas(client: TestClient) -> None:
    """A rag-demo token is rejected by voice persona endpoints."""
    _create_code(client, "rag-isolation-code", "rag-demo")
    redeem = client.post("/api/access/redeem", json={"code": "rag-isolation-code"})
    rag_headers = {"Authorization": f"Bearer {redeem.json()['access_token']}"}

    response = client.get("/api/voice/personas", headers=rag_headers)
    assert response.status_code == 403


def test_voice_personas_are_scoped_to_voice_demo_experience(
    client: TestClient, db_session: Session
) -> None:
    """Voice personas are stored with experience_id='voice-demo'."""
    headers = voice_access_headers(client, "persona-scope-code")
    persona_id = create_voice_persona(client, headers, name="Scoped Persona")

    record = db_session.get(VoicePersona, persona_id)
    assert record is not None
    assert record.experience_id == "voice-demo"


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


def test_admin_can_create_persona_for_any_experience(client: TestClient) -> None:
    """Admin API creates a persona for an arbitrary experience_id."""
    response = client.post(
        "/api/internal/admin/voice/experiences/voice-demo/personas",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={
            "name": "Admin Persona",
            "instructions": "Admin-created instructions.",
        },
    )
    assert response.status_code == 201
    assert response.json()["experience_id"] == "voice-demo"


def test_admin_can_upsert_config(client: TestClient) -> None:
    """Admin API creates or updates voice experience config."""
    response = client.put(
        "/api/internal/admin/voice/experiences/voice-demo/config",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"voice_name": "eve", "voice_provider": "xai"},
    )
    assert response.status_code == 200
    assert response.json()["voice_name"] == "eve"
    assert response.json()["voice_provider"] == "xai"


def test_admin_can_patch_persona(client: TestClient) -> None:
    """Admin PATCH updates a persona by id."""
    create_response = client.post(
        "/api/internal/admin/voice/experiences/voice-demo/personas",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"name": "Admin Update Persona", "instructions": "Original."},
    )
    persona_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/internal/admin/voice/experiences/voice-demo/personas/{persona_id}",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"instructions": "Updated via admin."},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["instructions"] == "Updated via admin."


def test_admin_can_deactivate_persona(client: TestClient) -> None:
    """Admin deactivate sets is_active=False."""
    create_response = client.post(
        "/api/internal/admin/voice/experiences/voice-demo/personas",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"name": "Admin Deactivate Persona", "instructions": "To remove."},
    )
    persona_id = create_response.json()["id"]

    deactivate_response = client.post(
        f"/api/internal/admin/voice/experiences/voice-demo/personas/{persona_id}/deactivate",
        headers={"X-Admin-Secret": "test-admin-secret"},
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False
