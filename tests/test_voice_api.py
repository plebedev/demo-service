"""Tests for the voice experience API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import json
from datetime import UTC, datetime

from app.models.voice import (
    VoiceConversationRecord,
    VoiceExperienceConfig,
    VoicePersona,
)


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
    payload = create_voice_config(
        client, headers, voice_name="eve", voice_provider="xai"
    )

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
    assert set(openai["voices"]) == {
        "alloy",
        "echo",
        "fable",
        "onyx",
        "nova",
        "shimmer",
    }


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


# ---------------------------------------------------------------------------
# Tool unit tests
# ---------------------------------------------------------------------------


def test_record_answer_is_registered_in_tool_registry() -> None:
    """record_answer tool is included in the voice tool registry."""
    from app.services.voice.tools import build_voice_tool_registry

    registry = build_voice_tool_registry()
    entry = registry.get("record_answer")
    assert entry.name == "record_answer"
    assert not entry.is_terminal


def test_record_answer_returns_recorded_status() -> None:
    """record_answer is a no-op that returns status='recorded'."""
    from app.services.voice.tools import build_voice_tool_registry

    registry = build_voice_tool_registry()
    result = registry.execute(
        "record_answer",
        {
            "question": "How many employees do you have?",
            "user_response": "We have about fifty people.",
            "derived_answer": "small",
        },
        {},
    )
    import json

    payload = json.loads(result)
    assert payload["status"] == "recorded"


def test_record_answer_tool_definition_has_required_fields() -> None:
    """record_answer tool definition exposes question, user_response, derived_answer."""
    from app.services.voice.tools import build_voice_tool_registry

    registry = build_voice_tool_registry()
    definitions = registry.tool_definitions()
    defn = next(d for d in definitions if d["name"] == "record_answer")
    props = defn["parameters"]["properties"]
    assert "question" in props
    assert "user_response" in props
    assert "derived_answer" in props


# ---------------------------------------------------------------------------
# Cost estimation unit tests
# ---------------------------------------------------------------------------


def test_estimate_cost_xai() -> None:
    """xAI rate: $3/hr = $0.000833/s."""
    from app.services.voice.cost import estimate_cost

    cost = estimate_cost("xai", 3600.0)
    assert abs(cost - 3.0) < 0.001  # one hour should be ~$3.00


def test_estimate_cost_xai_short_session() -> None:
    """xAI cost scales linearly with duration."""
    from app.services.voice.cost import estimate_cost

    cost_60s = estimate_cost("xai", 60.0)
    assert abs(cost_60s - 0.05) < 0.001  # 1 minute ≈ $0.05


def test_estimate_cost_openai() -> None:
    """OpenAI midpoint rate: $0.225/min = $0.00375/s."""
    from app.services.voice.cost import estimate_cost

    cost = estimate_cost("openai", 60.0)
    assert abs(cost - 0.225) < 0.001  # 1 minute ≈ $0.225


def test_estimate_cost_unknown_provider_returns_zero() -> None:
    """Unknown provider returns 0.0."""
    from app.services.voice.cost import estimate_cost

    assert estimate_cost("unknown_provider", 100.0) == 0.0


# ---------------------------------------------------------------------------
# Conversation history endpoints
# ---------------------------------------------------------------------------


def test_voice_history_requires_access_token(client: TestClient) -> None:
    """GET /api/voice/history returns 401 without a token."""
    response = client.get("/api/voice/history")
    assert response.status_code == 401


def test_voice_history_returns_empty_list_initially(client: TestClient) -> None:
    """GET /api/voice/history returns an empty list when no records exist."""
    headers = voice_access_headers(client, "hist-code-1")
    response = client.get("/api/voice/history", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"conversations": []}


def test_voice_history_detail_returns_404_for_missing(client: TestClient) -> None:
    """GET /api/voice/history/{id} returns 404 for a non-existent record."""
    headers = voice_access_headers(client, "hist-code-2")
    response = client.get("/api/voice/history/99999", headers=headers)
    assert response.status_code == 404


def test_voice_history_stores_and_retrieves_record(
    client: TestClient, db_session: Session
) -> None:
    """Directly insert a VoiceConversationRecord; verify list + detail endpoints."""
    transcript = [
        {"role": "advisor", "text": "Hello, how can I help?"},
        {"role": "user", "text": "I have a question."},
        {
            "role": "tool_call",
            "tool_name": "record_answer",
            "args": {"question": "q", "user_response": "r", "derived_answer": "d"},
        },
    ]
    record = VoiceConversationRecord(
        experience_id="voice-demo",
        call_sid="test-call-sid-history-001",
        provider="xai",
        voice="eve",
        started_at=datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 9, 10, 1, 30, tzinfo=UTC),
        duration_seconds=90.0,
        input_audio_seconds=40.0,
        output_audio_seconds=50.0,
        estimated_cost_usd=round(90.0 * 3.0 / 3600, 6),
        transcript_json=json.dumps(transcript),
    )
    db_session.add(record)
    db_session.commit()

    headers = voice_access_headers(client, "hist-code-3")

    list_response = client.get("/api/voice/history", headers=headers)
    assert list_response.status_code == 200
    conversations = list_response.json()["conversations"]
    assert len(conversations) == 1
    summary = conversations[0]
    assert summary["call_sid"] == "test-call-sid-history-001"
    assert summary["provider"] == "xai"
    assert summary["voice"] == "eve"
    assert summary["duration_seconds"] == 90.0
    assert summary["entry_count"] == 3
    assert "transcript" not in summary  # list view omits transcript

    detail_response = client.get(f"/api/voice/history/{summary['id']}", headers=headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["call_sid"] == "test-call-sid-history-001"
    assert len(detail["transcript"]) == 3
    assert detail["transcript"][0]["role"] == "advisor"
    assert detail["transcript"][2]["role"] == "tool_call"
