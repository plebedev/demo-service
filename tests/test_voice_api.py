"""Tests for the voice experience API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
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
    tool_names: list[str] | None = None,
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
            "tool_names": tool_names,
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
        "ash",
        "ballad",
        "cedar",
        "coral",
        "echo",
        "marin",
        "sage",
        "shimmer",
        "verse",
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
            "tool_names": ["record_answer", "end_conversation"],
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Employer Advisor"
    assert payload["instructions"] == "You are a workforce advisor."
    assert payload["capabilities"] == "Workforce readiness assessment."
    assert payload["tool_config"] is None
    assert payload["tool_names"] == ["record_answer", "end_conversation"]
    assert payload["is_active"] is True
    assert payload["experience_id"] == "voice-demo"


def test_voice_persona_rejects_unknown_tool_names(client: TestClient) -> None:
    """POST /api/voice/personas rejects tools outside the voice registry."""
    headers = voice_access_headers(client, "persona-bad-tool-code")
    response = client.post(
        "/api/voice/personas",
        headers=headers,
        json={
            "name": "Bad Tool Advisor",
            "instructions": "Use a missing tool.",
            "tool_names": ["record_answer", "normalize_input"],
        },
    )

    assert response.status_code == 400
    assert "Unknown voice tool" in response.json()["detail"]


def test_voice_persona_legacy_tool_names_default(
    client: TestClient, db_session: Session
) -> None:
    """Personas without tool_names_json keep the legacy voice tool set."""
    persona = VoicePersona(
        experience_id="voice-demo",
        name="Legacy Advisor",
        name_key="legacy advisor",
        instructions="Legacy instructions.",
        tool_names_serialized=None,
    )
    db_session.add(persona)
    db_session.commit()

    headers = voice_access_headers(client, "persona-legacy-tools-code")
    response = client.get("/api/voice/personas", headers=headers)

    assert response.status_code == 200
    payload = response.json()["personas"][0]
    assert payload["tool_names"] == [
        "assess_employer_readiness",
        "end_conversation",
        "record_answer",
    ]


def test_voice_persona_patch_round_trips_tool_names(client: TestClient) -> None:
    """PATCH /api/voice/personas/{id} persists the selected tool list."""
    headers = voice_access_headers(client, "persona-tool-patch-code")
    persona_id = create_voice_persona(
        client,
        headers,
        name="Tool Patch Advisor",
        tool_names=["record_answer"],
    )

    response = client.patch(
        f"/api/voice/personas/{persona_id}",
        headers=headers,
        json={"tool_names": ["prepare_meeting_context", "end_conversation"]},
    )

    assert response.status_code == 200
    assert response.json()["tool_names"] == [
        "prepare_meeting_context",
        "end_conversation",
    ]


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


def test_admin_persona_round_trips_tool_names(client: TestClient) -> None:
    """Admin persona endpoints support explicit voice tool selection."""
    create_response = client.post(
        "/api/internal/admin/voice/experiences/voice-demo/personas",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={
            "name": "Admin Tool Persona",
            "instructions": "Meeting prep.",
            "tool_names": ["prepare_meeting_context", "end_conversation"],
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["tool_names"] == [
        "prepare_meeting_context",
        "end_conversation",
    ]

    persona_id = create_response.json()["id"]
    patch_response = client.patch(
        f"/api/internal/admin/voice/experiences/voice-demo/personas/{persona_id}",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"tool_names": ["record_answer"]},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["tool_names"] == ["record_answer"]


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
    """record_answer tool is included in the shared tool registry."""
    from app.services.tool_registry import build_tool_registry

    registry = build_tool_registry()
    entry = registry.get("record_answer")
    assert entry.name == "record_answer"
    assert not entry.is_terminal


def test_voice_tools_are_registered_in_shared_tool_registry() -> None:
    """All fixed voice tools are discovered from the shared registry."""
    from app.services.tool_registry import build_tool_registry

    registry = build_tool_registry()

    assert registry.get("assess_employer_readiness").is_terminal is False
    assert registry.get("record_answer").is_terminal is False
    assert registry.get("end_conversation").is_terminal is True
    assert registry.get("warm_transfer_call").is_terminal is False


def test_record_answer_returns_recorded_status() -> None:
    """record_answer is a no-op that returns status='recorded'."""
    from app.services.tool_registry import build_tool_registry

    registry = build_tool_registry()
    result = registry.execute_json(
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
    from app.api.routes.voice import VOICE_TOOL_NAMES
    from app.services.tool_registry import build_tool_registry

    registry = build_tool_registry()
    definitions = registry.tool_definitions(VOICE_TOOL_NAMES)
    defn = next(d for d in definitions if d["name"] == "record_answer")
    props = defn["parameters"]["properties"]
    assert "question" in props
    assert "user_response" in props
    assert "derived_answer" in props


def test_voice_registry_scope_excludes_workflow_tools() -> None:
    """The voice-scoped registry only exposes configured voice tools."""
    from app.api.routes.voice import VOICE_TOOL_NAMES
    from app.services.tool_registry import build_tool_registry

    registry = build_tool_registry().scoped(VOICE_TOOL_NAMES)

    assert {entry.name for entry in registry.resolve()} == set(VOICE_TOOL_NAMES)
    with pytest.raises(KeyError, match="Unknown tool"):
        registry.get("normalize_input")


def test_voice_tools_endpoint_lists_meeting_prep_tool(client: TestClient) -> None:
    """GET /api/voice/tools returns discoverable voice tool metadata."""
    headers = voice_access_headers(client, "voice-tools-code")

    response = client.get("/api/voice/tools", headers=headers)

    assert response.status_code == 200
    tools = response.json()["tools"]
    meeting_tool = next(t for t in tools if t["name"] == "prepare_meeting_context")
    assert meeting_tool["is_terminal"] is False
    assert "live web lookup" in meeting_tool["description"].lower()
    transfer_tool = next(t for t in tools if t["name"] == "warm_transfer_call")
    assert transfer_tool["is_terminal"] is False
    assert "warm transfer" in transfer_tool["description"].lower()


def test_warm_transfer_call_rejects_non_e164_input() -> None:
    """warm_transfer_call enforces strict E.164 input format."""
    from pydantic import ValidationError

    from app.services.tool_registry import build_tool_registry

    registry = build_tool_registry()
    with pytest.raises(ValidationError):
        registry.execute_json(
            "warm_transfer_call",
            {"transfer_to_phone_number": "6177100171"},
            {},
        )


def test_warm_transfer_call_posts_to_sbc_gateway(monkeypatch) -> None:
    """warm_transfer_call sends the expected payload to the SBC control endpoint."""
    from app.services.tool_registry import build_tool_registry
    from app.services.voice import tools as voice_tools

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return

    def fake_post(url: str, json: dict[str, object], timeout: float):  # type: ignore[override]
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(voice_tools.httpx, "post", fake_post)

    registry = build_tool_registry()
    raw = registry.execute_json(
        "warm_transfer_call",
        {"transfer_to_phone_number": "+16177100171"},
        {
            "warm_transfer": {
                "gateway_base_url": "http://rust-sbc-gateway.demo.svc.cluster.local:8082",
                "trunk_host": "peter-voice-demo.sip.twilio.com",
                "twilio_number": "+17817346618",
                "trunk_port": 5060,
                "timeout_seconds": 7.5,
            },
            "_runtime": {"session_id": "CA123456789"},
        },
    )
    payload = json.loads(raw)

    assert payload["status"] == "started"
    assert payload["session_id"] == "CA123456789"
    assert captured["url"] == (
        "http://rust-sbc-gateway.demo.svc.cluster.local:8082"
        "/api/internal/transfer/start"
    )
    assert captured["timeout"] == 7.5
    assert captured["json"] == {
        "session_id": "CA123456789",
        "target_phone": "+16177100171",
        "twilio_number": "+17817346618",
        "trunk_host": "peter-voice-demo.sip.twilio.com",
        "trunk_port": 5060,
    }


def test_prepare_meeting_context_tool_returns_limitations(monkeypatch) -> None:
    """Meeting prep output is structured and explicit about no live lookup."""
    from app.services.tool_registry import build_tool_registry
    from app.services.voice import tools as voice_tools

    monkeypatch.setattr(
        voice_tools,
        "_generate_meeting_prep_context",
        lambda input, tool_config: {
            "summary": "Use a partnership framing for Acme.",
            "talking_points": ["Lead with shared outcomes."],
            "watchout": "Do not imply verified current news.",
            "recommended_next_question": "What would make this meeting successful?",
        },
    )

    registry = build_tool_registry()
    raw = registry.execute_json(
        "prepare_meeting_context",
        {"company_name": "Acme", "meeting_purpose": "partnership discussion"},
        {},
    )
    payload = json.loads(raw)

    assert payload["company_name"] == "Acme"
    assert payload["meeting_purpose"] == "partnership discussion"
    assert payload["talking_points"] == ["Lead with shared outcomes."]
    assert "does not browse the web" in payload["limitations"]


def test_async_tool_result_waits_for_response_done_when_active(monkeypatch) -> None:
    """Async tool output is appended after the active response finishes."""
    import asyncio

    from app.api.routes import voice as voice_routes

    order: list[str] = []

    async def fake_execute_tool(entry, args, tool_config):
        order.append("tool_started")
        await asyncio.sleep(0)
        return '{"status":"recorded"}'

    monkeypatch.setattr(voice_routes, "_execute_voice_tool", fake_execute_tool)

    class FakeVoiceClient:
        def __init__(self) -> None:
            self.events = [
                {"type": "response.created", "response": {"id": "resp_1"}},
                {
                    "type": "response.function_call_arguments.done",
                    "call_id": "call_1",
                    "name": "record_answer",
                    "arguments": json.dumps(
                        {
                            "question": "What is the meeting goal?",
                            "user_response": "Partnership.",
                            "derived_answer": "partnership",
                        }
                    ),
                },
                {"type": "response.done"},
            ]

        async def receive(self) -> dict:
            if not self.events:
                raise RuntimeError("done")
            event = self.events.pop(0)
            order.append(event["type"])
            return event

        async def send_tool_result(self, call_id: str, output: str) -> None:
            order.append("send_tool_result")

        async def cancel_response(self) -> None:
            order.append("cancel_response")

    class FakeWebSocket:
        async def send_text(self, text: str) -> None:
            order.append("ws_send_text")

        async def close(self) -> None:
            order.append("ws_close")

    asyncio.run(
        voice_routes._handle_xai_to_twilio(
            FakeWebSocket(),
            FakeVoiceClient(),
            stream_sid_ref=["stream_1"],
            call_sid_ref=["call_1"],
            conv_ref=[None],
            pending_tool_calls={},
        )
    )

    assert order.index("response.done") < order.index("send_tool_result")


def test_openai_voice_client_uses_ga_realtime_session_shape() -> None:
    """OpenAI session.update uses the GA nested audio schema."""
    from app.services.voice.openai_client import OpenAiVoiceClient

    client = OpenAiVoiceClient(api_key="test-key", model="gpt-realtime-2")
    sent: list[dict] = []  # type: ignore[type-arg]

    async def fake_send(message: dict) -> None:  # type: ignore[type-arg]
        sent.append(message)

    client._send = fake_send  # type: ignore[method-assign]

    import asyncio

    asyncio.run(
        client.configure_session(
            instructions="Say hello.",
            tools=[{"type": "function", "name": "record_answer"}],
            voice="marin",
            audio_format={"type": "audio/pcmu", "rate": 8000},
        )
    )

    assert sent == [
        {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": "gpt-realtime-2",
                "instructions": (
                    "Say hello.\n\nRespond only in English unless the user "
                    "explicitly asks for another language."
                ),
                "output_modalities": ["audio"],
                "tools": [{"type": "function", "name": "record_answer"}],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "transcription": {
                            "model": "gpt-4o-mini-transcribe",
                            "language": "en",
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.85,
                            "silence_duration_ms": 0,
                        },
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "voice": "marin",
                    },
                },
            },
        }
    ]
    assert "input_audio_format" not in sent[0]["session"]
    assert "output_audio_format" not in sent[0]["session"]
    assert "input_audio_transcription" not in sent[0]["session"]


def test_openai_voice_client_transcodes_bridge_audio() -> None:
    """OpenAI receives PCM16/24k while the app bridge keeps μ-law/8k."""
    import base64
    import struct

    from app.services.voice.openai_client import (
        _decode_mulaw_sample,
        _encode_mulaw_sample,
        _mulaw_8khz_b64_to_pcm16_24khz_b64,
        _pcm16_24khz_b64_to_mulaw_8khz_b64,
    )

    mulaw_10ms = bytes([_encode_mulaw_sample(0)] * 80)
    pcm_b64 = _mulaw_8khz_b64_to_pcm16_24khz_b64(
        base64.b64encode(mulaw_10ms).decode("ascii")
    )
    pcm = base64.b64decode(pcm_b64)
    assert len(pcm) == 480  # 80 samples at 8 kHz -> 240 samples at 24 kHz PCM16
    assert struct.unpack("<h", pcm[:2])[0] == _decode_mulaw_sample(mulaw_10ms[0])

    bridge_b64 = _pcm16_24khz_b64_to_mulaw_8khz_b64(pcm_b64)
    bridge_audio = base64.b64decode(bridge_b64)
    assert len(bridge_audio) == 80
    assert set(bridge_audio) == {mulaw_10ms[0]}


def test_openai_voice_client_connect_does_not_send_beta_header(monkeypatch) -> None:
    """OpenAI Realtime GA connection should not opt into the retired beta shape."""
    from app.services.voice.openai_client import OpenAiVoiceClient

    captured: dict[str, object] = {}

    async def fake_connect(url: str, additional_headers: dict[str, str]):
        captured["url"] = url
        captured["headers"] = additional_headers
        return object()

    monkeypatch.setattr(
        "websockets.asyncio.client.connect",
        fake_connect,
    )

    import asyncio

    client = OpenAiVoiceClient(api_key="test-key", model="gpt-realtime-2")
    asyncio.run(client._connect())

    assert captured["url"] == "wss://api.openai.com/v1/realtime?model=gpt-realtime-2"
    assert captured["headers"] == {"Authorization": "Bearer test-key"}


def test_stream_instructions_ignore_synthesized_greeting() -> None:
    """The realtime opening turn is controlled by persona instructions."""
    from app.api.routes.voice import _build_stream_instructions

    persona = VoicePersona(
        experience_id="voice-demo",
        name="Advisor",
        name_key="advisor",
        instructions="Ask careful intake questions.",
    )
    cfg = VoiceExperienceConfig(
        experience_id="voice-demo",
        voice_name="marin",
        synthesized_greeting="Hi, I am ready to help with workforce planning.",
    )

    instructions = _build_stream_instructions(
        persona,
        "Tool instructions:\n- record_answer: Record answers.",
    )

    assert instructions.startswith("Ask careful intake questions.")
    assert cfg.synthesized_greeting not in instructions
    assert "Tool instructions:" in instructions


def test_resolve_voice_name_falls_back_for_stale_provider_config() -> None:
    """Provider switches should not pass an xAI voice into OpenAI Realtime."""
    from app.api.routes.voice import _resolve_voice_name

    cfg = VoiceExperienceConfig(
        experience_id="voice-demo",
        voice_name="eve",
        voice_provider="openai",
    )

    assert _resolve_voice_name(cfg, "openai") == "marin"
    assert _resolve_voice_name(cfg, "xai") == "eve"


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
