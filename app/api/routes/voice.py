"""Voice experience routes: Twilio webhook, Media Streams bridge, browser test, persona management."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

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
from app.models.voice import (
    VoiceConversationRecord,
    VoiceExperienceConfig,
    VoicePersona,
)
from app.schemas.voice import (
    VoiceConversationDetail,
    VoiceConversationListResponse,
    VoiceConversationSummary,
    VoiceExperienceConfigResponse,
    VoiceExperienceConfigUpsertRequest,
    VoicePersonaCreateRequest,
    VoicePersonaListResponse,
    VoicePersonaResponse,
    VoicePersonaUpdateRequest,
    VoiceProviderInfo,
    VoiceProvidersResponse,
    VoiceToolInfo,
    VoiceToolsResponse,
)
from app.services.voice.base_client import VoiceClient
from app.services.voice.cost import estimate_cost
from app.services.voice.factory import get_voice_client
from app.services.voice.greeting import refresh_greeting_if_needed
from app.services.voice.session import create_session, get_session, remove_session
from app.services.tool_registry import ToolRegistry, build_tool_registry

logger = logging.getLogger(__name__)

LEGACY_VOICE_TOOL_NAMES = [
    "assess_employer_readiness",
    "end_conversation",
    "record_answer",
]
VOICE_TOOL_NAMES = [
    "assess_employer_readiness",
    "end_conversation",
    "prepare_meeting_context",
    "record_answer",
]

# Singleton registry built once at import time — stateless, shared across requests.
_voice_tool_registry: ToolRegistry = build_tool_registry().scoped(VOICE_TOOL_NAMES)

# Hardcoded provider/voice catalogue — matches factory._PROVIDER_MODELS keys.
_PROVIDER_VOICES: dict[str, list[str]] = {
    "xai": ["eve", "ara", "rex", "sal", "leo"],
    "openai": [
        "marin",
        "cedar",
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "sage",
        "shimmer",
        "verse",
    ],
}
_PROVIDER_NAMES: dict[str, str] = {"xai": "xAI", "openai": "OpenAI"}

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
# Conversation accumulator — in-memory state for one WebSocket session
# ---------------------------------------------------------------------------


@dataclass
class ConversationAccumulator:
    """Tracks transcript entries and audio byte counts for a single session."""

    started_at: datetime
    provider: str
    voice: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    input_audio_bytes: int = 0
    output_audio_bytes: int = 0


def _acc_transcript(acc: ConversationAccumulator, role: str, delta: str) -> None:
    """Append delta to the last entry if same role, otherwise start a new entry."""
    if acc.transcript and acc.transcript[-1]["role"] == role:
        acc.transcript[-1]["text"] += delta
    else:
        acc.transcript.append({"role": role, "text": delta})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def _serialize_history_summary(
    rec: VoiceConversationRecord,
) -> VoiceConversationSummary:
    try:
        entries: list[Any] = json.loads(rec.transcript_json)
    except (json.JSONDecodeError, ValueError):
        entries = []
    return VoiceConversationSummary(
        id=rec.id,
        call_sid=rec.call_sid,
        provider=rec.provider,
        voice=rec.voice,
        started_at=rec.started_at,
        ended_at=rec.ended_at,
        duration_seconds=rec.duration_seconds,
        input_audio_seconds=rec.input_audio_seconds,
        output_audio_seconds=rec.output_audio_seconds,
        estimated_cost_usd=rec.estimated_cost_usd,
        entry_count=len(entries),
    )


def _serialize_history_detail(rec: VoiceConversationRecord) -> VoiceConversationDetail:
    try:
        transcript: list[dict[str, Any]] = json.loads(rec.transcript_json)
    except (json.JSONDecodeError, ValueError):
        transcript = []
    return VoiceConversationDetail(
        id=rec.id,
        call_sid=rec.call_sid,
        provider=rec.provider,
        voice=rec.voice,
        started_at=rec.started_at,
        ended_at=rec.ended_at,
        duration_seconds=rec.duration_seconds,
        input_audio_seconds=rec.input_audio_seconds,
        output_audio_seconds=rec.output_audio_seconds,
        estimated_cost_usd=rec.estimated_cost_usd,
        entry_count=len(transcript),
        transcript=transcript,
    )


def _serialize_persona(persona: VoicePersona) -> VoicePersonaResponse:
    return VoicePersonaResponse(
        id=persona.id,
        experience_id=persona.experience_id,
        name=persona.name,
        instructions=persona.instructions,
        capabilities=persona.capabilities_serialized,
        tool_config=persona.tool_config_serialized,
        tool_names=_persona_tool_names(persona),
        is_active=persona.is_active,
        created_at=persona.created_at,
        updated_at=persona.updated_at,
    )


def _serialize_config(cfg: VoiceExperienceConfig) -> VoiceExperienceConfigResponse:
    return VoiceExperienceConfigResponse(
        id=cfg.id,
        experience_id=cfg.experience_id,
        voice_name=cfg.voice_name,
        voice_provider=cfg.voice_provider,
        synthesized_greeting=cfg.synthesized_greeting,
        greeting_synced_at=cfg.greeting_synced_at,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


def _get_active_persona_or_503(
    db: Session, experience_id: str, persona_id: int | None = None
) -> VoicePersona:
    """Return one active persona for an experience, or raise 503/404."""
    query = db.query(VoicePersona).filter(
        VoicePersona.experience_id == experience_id,
        VoicePersona.is_active == True,
    )
    if persona_id is not None:
        persona = query.filter(VoicePersona.id == persona_id).first()
        if persona is None:
            raise HTTPException(status_code=404, detail="Persona not found.")
        return persona
    persona = query.order_by(VoicePersona.id).first()
    if persona is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active voice persona configured for this experience.",
        )
    return persona


def _parse_tool_names(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Invalid tool_names_json; using legacy voice tools")
        return None
    if not isinstance(decoded, list) or not all(
        isinstance(item, str) for item in decoded
    ):
        logger.warning("Invalid tool_names_json shape; using legacy voice tools")
        return None
    return decoded


def _persona_tool_names(persona: VoicePersona) -> list[str]:
    parsed = _parse_tool_names(persona.tool_names_serialized)
    if parsed is None:
        return list(LEGACY_VOICE_TOOL_NAMES)
    return parsed


def _serialize_tool_names(tool_names: list[str] | None) -> str | None:
    if tool_names is None:
        return None
    _validate_voice_tool_names(tool_names)
    return json.dumps(tool_names)


def _validate_voice_tool_names(tool_names: list[str]) -> None:
    if len(tool_names) != len(set(tool_names)):
        raise HTTPException(status_code=400, detail="Duplicate voice tool names.")
    for tool_name in tool_names:
        try:
            _voice_tool_registry.get(tool_name)
        except KeyError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown voice tool: {tool_name}",
            ) from exc


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


async def _execute_voice_tool(
    entry: Any, args: dict[str, Any], tool_config: dict[str, Any]
) -> str:
    """Execute a voice tool without blocking the realtime receive loop."""
    return cast(str, await entry.execute_json_async(args, tool_config))


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
    persona_id: int | None = Query(default=None),
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

    # Read per-experience config before opening the voice client so we can
    # honour a per-experience provider override.
    voice_cfg_for_stream = (
        db.query(VoiceExperienceConfig)
        .filter(VoiceExperienceConfig.experience_id == ExperienceId.VOICE_DEMO)
        .first()
    )
    provider_override = (
        voice_cfg_for_stream.voice_provider if voice_cfg_for_stream else None
    )

    try:
        voice_client = get_voice_client(settings, provider=provider_override)
    except (RuntimeError, ValueError) as exc:
        logger.error("Voice provider not configured: %s", exc)
        await websocket.close(code=1011)
        return

    call_sid_ref: list[str | None] = [None]
    stream_sid_ref: list[str | None] = [None]
    conv_ref: list[ConversationAccumulator | None] = [None]
    pending_tool_calls: dict[str, dict[str, Any]] = {}

    try:
        async with voice_client as vc:
            input_task = asyncio.create_task(
                _handle_twilio_messages(
                    websocket,
                    vc,
                    db,
                    settings,
                    call_sid_ref=call_sid_ref,
                    stream_sid_ref=stream_sid_ref,
                    conv_ref=conv_ref,
                    pending_tool_calls=pending_tool_calls,
                    persona_id=persona_id,
                )
            )
            output_task = asyncio.create_task(
                _handle_xai_to_twilio(
                    websocket,
                    vc,
                    stream_sid_ref=stream_sid_ref,
                    call_sid_ref=call_sid_ref,
                    conv_ref=conv_ref,
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
        if conv_ref[0] is not None and call_sid_ref[0]:
            acc = conv_ref[0]
            ended_at = datetime.now(UTC)
            wall_secs = (ended_at - acc.started_at).total_seconds()
            input_secs = acc.input_audio_bytes / 8000.0
            output_secs = acc.output_audio_bytes / 8000.0
            cost = estimate_cost(acc.provider, wall_secs)
            try:
                record = VoiceConversationRecord(
                    experience_id=ExperienceId.VOICE_DEMO,
                    call_sid=call_sid_ref[0],
                    provider=acc.provider,
                    voice=acc.voice,
                    started_at=acc.started_at,
                    ended_at=ended_at,
                    duration_seconds=round(wall_secs, 3),
                    input_audio_seconds=round(input_secs, 3),
                    output_audio_seconds=round(output_secs, 3),
                    estimated_cost_usd=cost,
                    transcript_json=json.dumps(acc.transcript),
                )
                db.add(record)
                db.commit()
                logger.info(
                    "Conversation persisted: call=%s duration=%.1fs cost=$%.4f",
                    call_sid_ref[0],
                    wall_secs,
                    cost,
                )
            except Exception:
                logger.exception(
                    "Failed to persist conversation history for call %s",
                    call_sid_ref[0],
                )


async def _handle_twilio_messages(
    ws: WebSocket,
    vc: VoiceClient,
    db: Session,
    settings: Settings,
    call_sid_ref: list[str | None],
    stream_sid_ref: list[str | None],
    conv_ref: list[ConversationAccumulator | None],
    pending_tool_calls: dict[str, dict[str, Any]],
    persona_id: int | None = None,
) -> None:
    """Receive Twilio Media Streams events and forward audio to the voice provider."""
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

            try:
                persona = _get_active_persona_or_503(
                    db, ExperienceId.VOICE_DEMO, persona_id=persona_id
                )
            except HTTPException as exc:
                await ws.close(code=4004 if exc.status_code == 404 else 1011)
                break
            voice_cfg = (
                db.query(VoiceExperienceConfig)
                .filter(VoiceExperienceConfig.experience_id == ExperienceId.VOICE_DEMO)
                .first()
            )
            # Resolve the effective provider so it can be stored in history.
            resolved_provider = (
                voice_cfg.voice_provider
                if voice_cfg and voice_cfg.voice_provider
                else settings.voice_provider
            )
            voice = _resolve_voice_name(voice_cfg, resolved_provider)
            tool_config = _load_tool_config(persona)
            tool_names = _persona_tool_names(persona)
            persona_tool_registry = _voice_tool_registry.scoped(tool_names)
            create_session(
                session_id=call_sid,
                experience_id=ExperienceId.VOICE_DEMO,
                persona_id=persona.id,
                persona_instructions=persona.instructions,
                persona_tool_config=tool_config,
                tool_registry=persona_tool_registry,
            )
            conv_ref[0] = ConversationAccumulator(
                started_at=datetime.now(UTC),
                provider=resolved_provider,
                voice=voice,
            )
            tool_prompt = persona_tool_registry.prompt_block() or ""
            instructions = _build_stream_instructions(persona, tool_prompt)
            await vc.configure_session(
                instructions=instructions,
                tools=persona_tool_registry.tool_definitions(),
                voice=voice,
                audio_format={"type": "audio/pcmu", "rate": 8000},
            )
            await vc.start_response()
            logger.info("Voice stream started: call=%s", call_sid)

        elif event == "media":
            payload = msg.get("media", {}).get("payload", "")
            if payload:
                await vc.send_audio(payload)
                if conv_ref[0] is not None:
                    try:
                        conv_ref[0].input_audio_bytes += len(base64.b64decode(payload))
                    except Exception:
                        pass

        elif event == "stop":
            if call_sid_ref[0]:
                remove_session(call_sid_ref[0])
            logger.info("Voice stream stopped: call=%s", call_sid_ref[0])
            break


async def _handle_xai_to_twilio(
    ws: WebSocket,
    vc: VoiceClient,
    stream_sid_ref: list[str | None],
    call_sid_ref: list[str | None],
    conv_ref: list[ConversationAccumulator | None],
    pending_tool_calls: dict[str, dict[str, Any]],
) -> None:
    """Receive voice provider events and forward audio + transcripts + tool results to caller."""
    close_after_response = False
    current_response_id: str | None = None
    cancelled_response_id: str | None = None
    response_active = False  # True only while a response is in progress
    ready_tool_results: list[tuple[str, str]] = []
    tool_result_lock = asyncio.Lock()
    active_tool_tasks: set[asyncio.Task[None]] = set()

    async def send_or_queue_tool_result(call_id: str, result: str) -> None:
        to_send: list[tuple[str, str]] = []
        async with tool_result_lock:
            if response_active:
                ready_tool_results.append((call_id, result))
            else:
                to_send.append((call_id, result))
        for result_call_id, result_output in to_send:
            await vc.send_tool_result(result_call_id, result_output)

    async def flush_ready_tool_results() -> None:
        async with tool_result_lock:
            to_send = list(ready_tool_results)
            ready_tool_results.clear()
        for result_call_id, result_output in to_send:
            await vc.send_tool_result(result_call_id, result_output)

    async def run_tool_call(
        call_id: str,
        entry: Any,
        args: dict[str, Any],
        tool_config: dict[str, Any],
    ) -> None:
        try:
            result = await _execute_voice_tool(entry, args, tool_config)
        except Exception:
            logger.exception(
                "Voice tool execution failed: name=%s call_id=%s call=%s",
                getattr(entry, "name", ""),
                call_id,
                call_sid_ref[0],
            )
            result = json.dumps(
                {
                    "error": "tool_execution_failed",
                    "message": "The tool result was not available.",
                }
            )
        await send_or_queue_tool_result(call_id, result)

    while True:
        try:
            event = await vc.receive()
        except Exception:
            break

        event_type = event.get("type", "")

        if event_type == "response.created":
            # Track the new response id so we know something is active.
            resp = event.get("response", {})
            resp_id = resp.get("id") if isinstance(resp, dict) else None
            if resp_id:
                current_response_id = resp_id
            async with tool_result_lock:
                response_active = True

        elif event_type == "input_audio_buffer.speech_started":
            if response_active:
                # Only cancel — and only mark as cancelled — when a response is
                # actually in progress.  Sending response.cancel when nothing is
                # active produces a response_cancel_not_active error from OpenAI
                # and, worse, sets cancelled_response_id to the NEXT response's
                # id, silently filtering its audio and freezing the conversation.
                cancelled_response_id = current_response_id
                await vc.cancel_response()
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
            if audio_b64 and conv_ref[0] is not None:
                try:
                    conv_ref[0].output_audio_bytes += len(base64.b64decode(audio_b64))
                except Exception:
                    pass

        elif event_type in (
            "response.output_audio_transcript.delta",
            "response.text.delta",
        ):
            delta = event.get("delta", "")
            await ws.send_text(json.dumps({"event": "transcript", "text": delta}))
            if delta and conv_ref[0] is not None:
                _acc_transcript(conv_ref[0], "advisor", delta)

        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "")
            if transcript:
                await ws.send_text(
                    json.dumps({"event": "user_transcript", "text": transcript})
                )
                if conv_ref[0] is not None:
                    conv_ref[0].transcript.append({"role": "user", "text": transcript})

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
                await ws.send_text(
                    json.dumps(
                        {"event": "tool_call", "tool_name": tool_name, "args": args}
                    )
                )
                if conv_ref[0] is not None:
                    conv_ref[0].transcript.append(
                        {"role": "tool_call", "tool_name": tool_name, "args": args}
                    )
                try:
                    session = get_session(call_sid_ref[0] or "")
                    tool_registry = (
                        session.tool_registry if session else _voice_tool_registry
                    )
                    entry = tool_registry.get(tool_name)
                except KeyError:
                    logger.warning("Unknown tool: %s", tool_name)
                    continue
                if entry.is_terminal:
                    close_after_response = True
                else:
                    tool_config = session.persona_tool_config if session else {}
                    task = asyncio.create_task(
                        run_tool_call(call_id, entry, args, tool_config)
                    )
                    active_tool_tasks.add(task)
                    task.add_done_callback(active_tool_tasks.discard)

        elif event_type == "response.done":
            async with tool_result_lock:
                response_active = False
            await flush_ready_tool_results()
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
            logger.error("Voice error event: %s", event.get("error", {}))

    if active_tool_tasks:
        await asyncio.gather(*list(active_tool_tasks), return_exceptions=True)
    async with tool_result_lock:
        response_is_idle = not response_active
    if response_is_idle:
        await flush_ready_tool_results()


async def _ws_iter(ws: WebSocket):  # type: ignore[no-untyped-def]
    """Yield text messages from a FastAPI WebSocket until disconnect."""
    while True:
        try:
            yield await ws.receive_text()
        except WebSocketDisconnect:
            return


def _build_stream_instructions(
    persona: VoicePersona,
    tool_prompt: str,
) -> str:
    """Build realtime instructions from persona guidance and tool rules."""
    parts = [persona.instructions]
    if tool_prompt:
        parts.append(tool_prompt)
    return "\n\n".join(parts)


def _resolve_voice_name(
    voice_cfg: VoiceExperienceConfig | None,
    provider: str,
) -> str:
    """Return a provider-compatible voice, tolerating stale cross-provider config."""
    provider_key = provider.lower()
    voices = _PROVIDER_VOICES.get(provider_key) or _PROVIDER_VOICES["xai"]
    configured_voice = voice_cfg.voice_name if voice_cfg is not None else None
    if configured_voice in voices:
        return configured_voice
    return voices[0]


# ---------------------------------------------------------------------------
# User-facing voice management routes (voice-demo access token required)
# Scoped to the voice-demo experience — mirrors RAG persona management pattern.
# ---------------------------------------------------------------------------

_EXPERIENCE_ID = ExperienceId.VOICE_DEMO


@router.get("/providers", response_model=VoiceProvidersResponse)
def list_voice_providers(
    claims: AccessTokenClaims = Depends(voice_access),
) -> VoiceProvidersResponse:
    """Return available voice providers and their voice options."""
    return VoiceProvidersResponse(
        providers=[
            VoiceProviderInfo(
                provider_id=pid,
                provider_name=_PROVIDER_NAMES[pid],
                voices=voices,
            )
            for pid, voices in _PROVIDER_VOICES.items()
        ]
    )


@router.get("/tools", response_model=VoiceToolsResponse)
def list_voice_tools(
    claims: AccessTokenClaims = Depends(voice_access),
) -> VoiceToolsResponse:
    """Return voice tools that can be enabled per persona."""
    return VoiceToolsResponse(
        tools=[
            VoiceToolInfo(
                name=entry.name,
                description=entry.description,
                is_terminal=entry.is_terminal,
            )
            for entry in _voice_tool_registry.resolve(VOICE_TOOL_NAMES)
        ]
    )


@router.get("/history", response_model=VoiceConversationListResponse)
def list_conversation_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    claims: AccessTokenClaims = Depends(voice_access),
    db: Session = Depends(get_db_session),
) -> VoiceConversationListResponse:
    """Return a paginated list of past voice conversations (no transcript body)."""
    records = (
        db.query(VoiceConversationRecord)
        .filter(VoiceConversationRecord.experience_id == _EXPERIENCE_ID)
        .order_by(VoiceConversationRecord.started_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return VoiceConversationListResponse(
        conversations=[_serialize_history_summary(r) for r in records]
    )


@router.get("/history/{record_id}", response_model=VoiceConversationDetail)
def get_conversation_detail(
    record_id: int,
    claims: AccessTokenClaims = Depends(voice_access),
    db: Session = Depends(get_db_session),
) -> VoiceConversationDetail:
    """Return a single conversation record including the full transcript."""
    record = db.get(VoiceConversationRecord, record_id)
    if record is None or record.experience_id != _EXPERIENCE_ID:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return _serialize_history_detail(record)


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
            voice_provider=payload.voice_provider,
        )
        db.add(cfg)
    else:
        cfg.voice_name = payload.voice_name
        cfg.voice_provider = payload.voice_provider  # type: ignore[assignment]
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
        tool_names_serialized=_serialize_tool_names(payload.tool_names),
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
    if payload.tool_names is not None:
        persona.tool_names_serialized = _serialize_tool_names(payload.tool_names)  # type: ignore[assignment]

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
            voice_provider=payload.voice_provider,
        )
        db.add(cfg)
    else:
        cfg.voice_name = payload.voice_name
        cfg.voice_provider = payload.voice_provider  # type: ignore[assignment]
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
        tool_names_serialized=_serialize_tool_names(payload.tool_names),
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
    if payload.tool_names is not None:
        persona.tool_names_serialized = _serialize_tool_names(payload.tool_names)  # type: ignore[assignment]

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
