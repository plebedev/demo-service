"""In-memory call session state for active voice calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.tool_registry import ToolRegistry


@dataclass
class VoiceCallSession:
    """State held for the duration of one active phone call or browser session."""

    session_id: str  # Twilio CallSid or browser-generated UUID
    experience_id: str
    persona_id: int
    persona_instructions: str
    persona_tool_config: dict[str, Any]
    tool_registry: ToolRegistry
    collected_answers: dict[str, str] = field(default_factory=dict)


_sessions: dict[str, VoiceCallSession] = {}


def create_session(
    session_id: str,
    experience_id: str,
    persona_id: int,
    persona_instructions: str,
    persona_tool_config: dict[str, Any],
    tool_registry: ToolRegistry,
) -> VoiceCallSession:
    """Create and store a new call session."""
    session = VoiceCallSession(
        session_id=session_id,
        experience_id=experience_id,
        persona_id=persona_id,
        persona_instructions=persona_instructions,
        persona_tool_config=persona_tool_config,
        tool_registry=tool_registry,
    )
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> VoiceCallSession | None:
    """Retrieve a call session by ID."""
    return _sessions.get(session_id)


def remove_session(session_id: str) -> None:
    """Remove a call session on call end."""
    _sessions.pop(session_id, None)
