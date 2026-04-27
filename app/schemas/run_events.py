"""Pydantic schemas for structured run execution events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.run_event import RunEventType


class RunEventPayload(BaseModel):
    """Structured event payload accepted by the recorder service."""

    event_type: RunEventType
    agent_role: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    handoff_source_role: str | None = None
    handoff_target_role: str | None = None
    post_processor_key: str | None = None
    message: str | None = None


class RunEventResponse(BaseModel):
    """Serialized run event for auditing and tests."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    event_type: RunEventType
    agent_role: str | None
    tool_name: str | None
    tool_arguments: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    handoff_source_role: str | None
    handoff_target_role: str | None
    post_processor_key: str | None
    message: str | None
    created_at: datetime
