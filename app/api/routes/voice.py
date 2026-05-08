"""Voice experience routes: Twilio webhook, Media Streams bridge, browser test, persona management."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.deps import require_admin_secret, require_experience_access
from app.core.config import Settings, get_settings
from app.core.experiences import ExperienceId
from app.core.security import AccessTokenClaims, verify_access_token
from app.db.session import get_db_session
from app.models.voice import VoiceExperienceConfig, VoicePersona
from app.schemas.voice import (
    VoiceExperienceConfigResponse,
    VoiceExperienceConfigUpsertRequest,
    VoicePersonaCreateRequest,
    VoicePersonaListResponse,
    VoicePersonaResponse,
    VoicePersonaUpdateRequest,
)
from app.services.voice.greeting import refresh_greeting_if_needed
from app.services.voice.session import create_session, get_session, remove_session
from app.services.voice.tools import VoiceToolRegistry, build_voice_tool_registry
from app.services.voice.xai_client import XaiVoiceClient

logger = logging.getLogger(__name__)

# Singleton registry built once at import time — stateless, shared across requests.
_voice_tool_registry: VoiceToolRegistry = build_voice_tool_registry()

# Public voice routes: Twilio webhook, Media Streams WS, browser WS, user-facing management
router = APIRouter(prefix="/api/voice", tags=["voice"])

# Internal admin routes (admin secret required, for ops/script use)
admin_router = APIRouter(
    prefix="/api/internal/admin/voice",
    tags=["internal-admin-voice"],
    dependencies=[Depends(require_admin_secret)],
)

voice_access = require_experience_access(ExperienceId.VOICE_DEMO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def _serialize_persona(persona: VoicePersona) -> VoicePersonaResponse:
    return VoicePersonaResponse(
        id=persona.id,
        experience_id=persona.experience_id,
        name=persona.name,
        instructions=persona.instructions,
        capabilities=persona.capabilities_serialized,
        tool_config=persona.tool_config_serialized,
        is_active=persona.is_active,
        created_at=persona.created_at,
        updated_at=persona.updated_at,
    )


def _serialize_config(cfg: VoiceExperienceConfig) -> VoiceExperienceConfigResponse:
    return VoiceExperienceConfigResponse(
        id=cfg.id,
        experience_id=cfg.experience_id,
        voice_name=cfg.voice_name,
        synthesized_greeting=cfg.synthesized_greeting,
        greeting_synced_at=cfg.greeting_synced_at,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


def _get_active_persona_or_503(db: Session, experience_id: str) -> VoicePersona:
    """Return the first active persona for an experience, or raise 503."""
    persona = (
        db.query(VoicePersona)
        .filter(
            VoicePersona.experience_id == experience_id,
            VoicePersona.is_active == True,
        )
        .order_by(VoicePersona.id)
        .first()
    )
    if persona is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active voice persona configured for this experience.",
        )
    return persona


def _load_tool_config(persona: VoicePersona) -> dict[str, Any]:
    if not persona.tool_config_serialized:
        return {}
    try:
        result: dict[str, Any] = json.loads(persona.tool_config_serialized)
        return result
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "Invalid tool_config_json on persona %d; using empty config", persona.id
        )
        return {}


def _validate_twilio_signature(
    request_url: str,
    post_params: dict[str, str],
    twilio_signature: str,
    auth_token: str,
) -> bool:
    """Validate a Twilio webhook request signature using HMAC-SHA1."""
    if post_params:
        sorted_params = "".join(f"{k}{v}" for k, v in sorted(post_params.items()))
        validation_string = request_url + sorted_params
    else:
        validation_string = request_url

    expected = base64.b64encode(
        hmac.new(
            auth_token.encode("utf-8"),
            validation_string.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")

    return hmac.compare_digest(expected, twilio_signature)


def _twiml_connect_stream(stream_url: str) -> str:
    """Return TwiML that opens a Twilio Media Stream WebSocket."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{stream_url}"/>'
        "</Connect>"
        "</Response>"
    )


# ---------------------------------------------------------------------------
# Twilio Voice webhook
# ---------------------------------------------------------------------------


@router.post("/inbound")
async def voice_inbound(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db_session),
) -> Response:
    """Receive an inbound Twilio Voice call and open a Media Stream."""
    if settings.twilio_auth_token:
        twilio_sig = request.headers.get("X-Twilio-Signature", "")
        form_data = dict(await request.form())
        post_params = {k: str(v) for k, v in form_data.items()}
        request_url = str(request.url)
        if not _validate_twilio_signature(
            request_url, post_params, twilio_sig, settings.twilio_auth_token
        ):
            logger.warning("Twilio signature validation failed from %s", request.client)
            return Response(status_code=403)

    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    scheme = request.headers.get("x-forwarded-proto", "https")
    ws_scheme = "wss" if scheme == "https" else "ws"
    stream_url = f"{ws_scheme}://{host}/api/voice/stream"

    return Response(content=_twiml_connect_stream(stream_url), media_type="text/xml")


# ---------------------------------------------------------------------------
# Twilio Media Streams WebSocket bridge
# ---------------------------------------------------------------------------


@router.websocket("/stream")
async def voice_stream(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db_session),
) -> None:
    """Bridge Twilio Media Streams (or browser test) audio to the xAI Voice Agent.

    Real Twilio calls connect without a token (authenticated via the webhook
    signature on /inbound).  Browser tests pass ?token=<access-token> to
    authenticate directly.
    """
    await websocket.accept()

    if token is not None:
        try:
            claims = verify_access_token(token, settings)
        except HTTPException:
            await websocket.close(code=4001)
            return
        if claims.experience_id != ExperienceId.VOICE_DEMO:
            await websocket.close(code=4003)
            return

    if not settings.xai_api_key:
        logger.error("XAI_API_KEY not configured; closing voice stream")
        await websocket.close(code=1011)
        return

    call_sid_ref: list[str | None] = [None]
    stream_sid_ref: list[str | None] = [None]
    pending_tool_calls: dict[str, dict[str, Any]] = {}

    try:
        async with XaiVoiceClient(
            api_key=settings.xai_api_key,
            model=settings.voice_xai_model,
        ) as xai:
            input_task = asyncio.create_task(
                _handle_twilio_messages(
                    websocket,
                    xai,
                    db,
                    settings,
                    call_sid_ref=call_sid_ref,
                    stream_sid_ref=stream_sid_ref,
                    pending_tool_calls=pending_tool_calls,
                )
            )
            output_task = asyncio.create_task(
                _handle_xai_to_twilio(
                    websocket,
                    xai,
                    stream_sid_ref=stream_sid_ref,
                    call_sid_ref=call_sid_ref,
                    pending_tool_calls=pending_tool_calls,
                )
            )
            done, pending = await asyncio.wait(
                [input_task, output_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception(
            "Unexpected error in voice stream for call %s", call_sid_ref[0]
        )
    finally:
        if call_sid_ref[0]:
            remove_session(call_sid_ref[0])


async def _handle_twilio_messages(
    ws: WebSocket,
    xai: XaiVoiceClient,
    db: Session,
    settings: Settings,
    call_sid_ref: list[str | None],
    stream_sid_ref: list[str | None],
    pending_tool_calls: dict[str, dict[str, Any]],
) -> None:
    """Receive Twilio Media Streams events and forward audio to xAI."""
    async for raw in _ws_iter(ws):
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        event = msg.get("event")

        if event == "start":
            start = msg.get("start", {})
            call_sid = start.get("callSid", "")
            call_sid_ref[0] = call_sid
            stream_sid_ref[0] = start.get("streamSid", "")

            persona = _get_active_persona_or_503(db, ExperienceId.VOICE_DEMO)
            voice_cfg = (
                db.query(VoiceExperienceConfig)
                .filter(VoiceExperienceConfig.experience_id == ExperienceId.VOICE_DEMO)
                .first()
            )
            voice_name = voice_cfg.voice_name if voice_cfg else "Eve"
            tool_config = _load_tool_config(persona)
            create_session(
                session_id=call_sid,
                experience_id=ExperienceId.VOICE_DEMO,
                persona_id=persona.id,
                persona_instructions=persona.instructions,
                persona_tool_config=tool_config,
                tool_registry=_voice_tool_registry,
            )
            tool_prompt = _voice_tool_registry.build_prompt_section()
            instructions = f"{persona.instructions}\n\n{tool_prompt}"
            await xai.configure_session(
                instructions=instructions,
                tools=_voice_tool_registry.xai_definitions(),
                voice=voice_name,
                audio_format={"type": "audio/pcmu", "rate": 8000},
            )
            await xai.start_response()
            logger.info("Voice stream started: call=%s", call_sid)

        elif event == "media":
            payload = msg.get("media", {}).get("payload", "")
            if payload:
                await xai.send_audio(payload)

        elif event == "stop":
            if call_sid_ref[0]:
                remove_session(call_sid_ref[0])
            logger.info("Voice stream stopped: call=%s", call_sid_ref[0])
            break


async def _handle_xai_to_twilio(
    ws: WebSocket,
    xai: XaiVoiceClient,
    stream_sid_ref: list[str | None],
    call_sid_ref: list[str | None],
    pending_tool_calls: dict[str, dict[str, Any]],
) -> None:
    """Receive xAI events and forward audio + transcripts + tool results to caller."""
    close_after_response = False
    current_response_id: str | None = None
    cancelled_response_id: str | None = None

    while True:
        try:
            event = await xai.receive()
        except Exception:
            break

        event_type = event.get("type", "")

        if event_type == "input_audio_buffer.speech_started":
            cancelled_response_id = current_response_id
            await xai.cancel_response()
            stream_sid = stream_sid_ref[0]
            if stream_sid:
                await ws.send_text(
                    json.dumps({"event": "clear", "streamSid": stream_sid})
                )

        elif event_type == "response.output_audio.delta":
            resp_id = event.get("response_id")
            if resp_id is not None:
                current_response_id = resp_id
            if resp_id is not None and resp_id == cancelled_response_id:
                continue
            audio_b64 = event.get("delta", "")
            stream_sid = stream_sid_ref[0]
            if audio_b64 and stream_sid:
                await ws.send_text(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": audio_b64},
                        }
                    )
                )

        elif event_type in (
            "response.output_audio_transcript.delta",
            "response.text.delta",
        ):
            await ws.send_text(
                json.dumps({"event": "transcript", "text": event.get("delta", "")})
            )

        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "")
            if transcript:
                await ws.send_text(
                    json.dumps({"event": "user_transcript", "text": transcript})
                )

        elif event_type == "response.function_call_arguments.delta":
            call_id = event.get("call_id", "")
            if call_id:
                if call_id not in pending_tool_calls:
                    pending_tool_calls[call_id] = {
                        "name": event.get("name", ""),
                        "args_buf": "",
                    }
                pending_tool_calls[call_id]["args_buf"] += event.get("delta", "")

        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id", "")
            if call_id:
                tool = pending_tool_calls.pop(call_id, None)
                tool_name = (tool["name"] if tool else None) or event.get("name", "")
                args_json = (
                    event.get("arguments") or (tool["args_buf"] if tool else "") or "{}"
                )
                logger.info(
                    "Tool call: name=%s call_id=%s call=%s",
                    tool_name,
                    call_id,
                    call_sid_ref[0],
                )
                try:
                    args: dict[str, Any] = json.loads(args_json)
                except (json.JSONDecodeError, ValueError):
                    args = {}
                try:
                    entry = _voice_tool_registry.get(tool_name)
                except KeyError:
                    logger.warning("Unknown tool: %s", tool_name)
                    continue
                if entry.is_terminal:
                    close_after_response = True
                else:
                    session = get_session(call_sid_ref[0] or "")
                    tool_config = session.persona_tool_config if session else {}
                    result = entry.execute(args, tool_config)
                    await xai.send_tool_result(call_id, result)

        elif event_type == "response.done":
            logger.info(
                "response.done: close_after_response=%s call=%s",
                close_after_response,
                call_sid_ref[0],
            )
            if close_after_response:
                await asyncio.sleep(0.4)
                await ws.send_text(json.dumps({"event": "end"}))
                await ws.close()
                break

        elif event_type == "error":
            logger.error("xAI error event: %s", event.get("error", {}))


async def _ws_iter(ws: WebSocket):  # type: ignore[no-untyped-def]
    """Yield text messages from a FastAPI WebSocket until disconnect."""
    while True:
        try:
            yield await ws.receive_text()
        except WebSocketDisconnect:
            return


# ---------------------------------------------------------------------------
# User-facing voice management routes (voice-demo access token required)
# Scoped to the voice-demo experience — mirrors RAG persona management pattern.
# ---------------------------------------------------------------------------

_EXPERIENCE_ID = ExperienceId.VOICE_DEMO


@router.get("/config", response_model=VoiceExperienceConfigResponse)
def get_voice_config(
    claims: AccessTokenClaims = Depends(voice_access),
    db: Session = Depends(get_db_session),
) -> VoiceExperienceConfigResponse:
    """Return the voice experience configuration."""
    cfg = (
        db.query(VoiceExperienceConfig)
        .filter(VoiceExperienceConfig.experience_id == _EXPERIENCE_ID)
        .first()
    )
    if cfg is None:
        raise HTTPException(
            status_code=404, detail="Voice experience not configured yet."
        )
    return _serialize_config(cfg)


@router.put("/config", response_model=VoiceExperienceConfigResponse)
def upsert_voice_config(
    payload: VoiceExperienceConfigUpsertRequest,
    background_tasks: BackgroundTasks,
    claims: AccessTokenClaims = Depends(voice_access),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoiceExperienceConfigResponse:
    """Create or update the voice experience configuration."""
    cfg = (
        db.query(VoiceExperienceConfig)
        .filter(VoiceExperienceConfig.experience_id == _EXPERIENCE_ID)
        .first()
    )
    if cfg is None:
        cfg = VoiceExperienceConfig(
            experience_id=_EXPERIENCE_ID,
            voice_name=payload.voice_name,
        )
        db.add(cfg)
    else:
        cfg.voice_name = payload.voice_name
    db.commit()
    db.refresh(cfg)
    background_tasks.add_task(refresh_greeting_if_needed, db, _EXPERIENCE_ID, settings)
    return _serialize_config(cfg)


@router.get("/personas", response_model=VoicePersonaListResponse)
def list_voice_personas(
    claims: AccessTokenClaims = Depends(voice_access),
    db: Session = Depends(get_db_session),
) -> VoicePersonaListResponse:
    """List all active voice personas."""
    personas = (
        db.query(VoicePersona)
        .filter(
            VoicePersona.experience_id == _EXPERIENCE_ID,
            VoicePersona.is_active == True,
        )
        .order_by(VoicePersona.id)
        .all()
    )
    return VoicePersonaListResponse(personas=[_serialize_persona(p) for p in personas])


@router.post("/personas", response_model=VoicePersonaResponse, status_code=201)
def create_voice_persona(
    payload: VoicePersonaCreateRequest,
    background_tasks: BackgroundTasks,
    claims: AccessTokenClaims = Depends(voice_access),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoicePersonaResponse:
    """Create a new voice persona."""
    name_key = _normalize_name(payload.name)
    existing = (
        db.query(VoicePersona)
        .filter(
            VoicePersona.experience_id == _EXPERIENCE_ID,
            VoicePersona.name_key == name_key,
            VoicePersona.is_active == True,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active persona with this name already exists.",
        )

    persona = VoicePersona(
        experience_id=_EXPERIENCE_ID,
        name=payload.name.strip(),
        name_key=name_key,
        instructions=payload.instructions,
        capabilities_serialized=payload.capabilities,
        tool_config_serialized=payload.tool_config,
        is_active=True,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    background_tasks.add_task(refresh_greeting_if_needed, db, _EXPERIENCE_ID, settings)
    return _serialize_persona(persona)


@router.patch("/personas/{persona_id}", response_model=VoicePersonaResponse)
def update_voice_persona(
    persona_id: int,
    payload: VoicePersonaUpdateRequest,
    background_tasks: BackgroundTasks,
    claims: AccessTokenClaims = Depends(voice_access),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoicePersonaResponse:
    """Update a voice persona's instructions, capabilities, or tool config."""
    persona = db.get(VoicePersona, persona_id)
    if persona is None or persona.experience_id != _EXPERIENCE_ID:
        raise HTTPException(status_code=404, detail="Persona not found.")

    if payload.instructions is not None:
        persona.instructions = payload.instructions
    if payload.capabilities is not None:
        persona.capabilities_serialized = payload.capabilities
    if payload.tool_config is not None:
        persona.tool_config_serialized = payload.tool_config

    db.commit()
    db.refresh(persona)
    background_tasks.add_task(refresh_greeting_if_needed, db, _EXPERIENCE_ID, settings)
    return _serialize_persona(persona)


@router.post("/personas/{persona_id}/deactivate", response_model=VoicePersonaResponse)
def deactivate_voice_persona(
    persona_id: int,
    background_tasks: BackgroundTasks,
    claims: AccessTokenClaims = Depends(voice_access),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoicePersonaResponse:
    """Soft-delete a voice persona."""
    persona = db.get(VoicePersona, persona_id)
    if persona is None or persona.experience_id != _EXPERIENCE_ID:
        raise HTTPException(status_code=404, detail="Persona not found.")

    persona.is_active = False
    db.commit()
    db.refresh(persona)
    background_tasks.add_task(refresh_greeting_if_needed, db, _EXPERIENCE_ID, settings)
    return _serialize_persona(persona)


# ---------------------------------------------------------------------------
# Admin routes (admin secret required — identical logic, for ops/script use)
# ---------------------------------------------------------------------------


@admin_router.get(
    "/experiences/{experience_id}/config",
    response_model=VoiceExperienceConfigResponse,
)
def admin_get_experience_config(
    experience_id: str,
    db: Session = Depends(get_db_session),
) -> VoiceExperienceConfigResponse:
    """Return the voice config for any experience."""
    cfg = (
        db.query(VoiceExperienceConfig)
        .filter(VoiceExperienceConfig.experience_id == experience_id)
        .first()
    )
    if cfg is None:
        raise HTTPException(
            status_code=404, detail="No config found for this experience."
        )
    return _serialize_config(cfg)


@admin_router.put(
    "/experiences/{experience_id}/config",
    response_model=VoiceExperienceConfigResponse,
)
def admin_upsert_experience_config(
    experience_id: str,
    payload: VoiceExperienceConfigUpsertRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoiceExperienceConfigResponse:
    """Create or update voice config for any experience."""
    cfg = (
        db.query(VoiceExperienceConfig)
        .filter(VoiceExperienceConfig.experience_id == experience_id)
        .first()
    )
    if cfg is None:
        cfg = VoiceExperienceConfig(
            experience_id=experience_id,
            voice_name=payload.voice_name,
        )
        db.add(cfg)
    else:
        cfg.voice_name = payload.voice_name
    db.commit()
    db.refresh(cfg)
    background_tasks.add_task(refresh_greeting_if_needed, db, experience_id, settings)
    return _serialize_config(cfg)


@admin_router.post(
    "/experiences/{experience_id}/refresh-greeting",
    response_model=VoiceExperienceConfigResponse,
)
def admin_refresh_greeting(
    experience_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoiceExperienceConfigResponse:
    """Trigger greeting re-synthesis for any experience."""
    cfg = (
        db.query(VoiceExperienceConfig)
        .filter(VoiceExperienceConfig.experience_id == experience_id)
        .first()
    )
    if cfg is None:
        raise HTTPException(
            status_code=404, detail="No config found for this experience."
        )
    background_tasks.add_task(refresh_greeting_if_needed, db, experience_id, settings)
    return _serialize_config(cfg)


@admin_router.get(
    "/experiences/{experience_id}/personas",
    response_model=VoicePersonaListResponse,
)
def admin_list_personas(
    experience_id: str,
    db: Session = Depends(get_db_session),
) -> VoicePersonaListResponse:
    """List all active personas for any experience."""
    personas = (
        db.query(VoicePersona)
        .filter(
            VoicePersona.experience_id == experience_id,
            VoicePersona.is_active == True,
        )
        .order_by(VoicePersona.id)
        .all()
    )
    return VoicePersonaListResponse(personas=[_serialize_persona(p) for p in personas])


@admin_router.post(
    "/experiences/{experience_id}/personas",
    response_model=VoicePersonaResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_persona(
    experience_id: str,
    payload: VoicePersonaCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoicePersonaResponse:
    """Create a new voice persona for any experience."""
    name_key = _normalize_name(payload.name)
    existing = (
        db.query(VoicePersona)
        .filter(
            VoicePersona.experience_id == experience_id,
            VoicePersona.name_key == name_key,
            VoicePersona.is_active == True,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active persona with this name already exists.",
        )

    persona = VoicePersona(
        experience_id=experience_id,
        name=payload.name.strip(),
        name_key=name_key,
        instructions=payload.instructions,
        capabilities_serialized=payload.capabilities,
        tool_config_serialized=payload.tool_config,
        is_active=True,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    background_tasks.add_task(refresh_greeting_if_needed, db, experience_id, settings)
    return _serialize_persona(persona)


@admin_router.patch(
    "/experiences/{experience_id}/personas/{persona_id}",
    response_model=VoicePersonaResponse,
)
def admin_update_persona(
    experience_id: str,
    persona_id: int,
    payload: VoicePersonaUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoicePersonaResponse:
    """Update a persona for any experience."""
    persona = db.get(VoicePersona, persona_id)
    if persona is None or persona.experience_id != experience_id:
        raise HTTPException(status_code=404, detail="Persona not found.")

    if payload.instructions is not None:
        persona.instructions = payload.instructions
    if payload.capabilities is not None:
        persona.capabilities_serialized = payload.capabilities
    if payload.tool_config is not None:
        persona.tool_config_serialized = payload.tool_config

    db.commit()
    db.refresh(persona)
    background_tasks.add_task(refresh_greeting_if_needed, db, experience_id, settings)
    return _serialize_persona(persona)


@admin_router.post(
    "/experiences/{experience_id}/personas/{persona_id}/deactivate",
    response_model=VoicePersonaResponse,
)
def admin_deactivate_persona(
    experience_id: str,
    persona_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VoicePersonaResponse:
    """Soft-delete a persona for any experience."""
    persona = db.get(VoicePersona, persona_id)
    if persona is None or persona.experience_id != experience_id:
        raise HTTPException(status_code=404, detail="Persona not found.")

    persona.is_active = False
    db.commit()
    db.refresh(persona)
    background_tasks.add_task(refresh_greeting_if_needed, db, experience_id, settings)
    return _serialize_persona(persona)
