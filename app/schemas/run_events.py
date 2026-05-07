"""Pydantic schemas for structured run execution events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.run_event import RunEventType


class RunEventPayload(BaseModel):
    """Structured event payload accepted by the recorder service."""

    event_type: RunEventType = Field(
        description="Type of workflow event being recorded"
    )
    status: str | None = Field(
        default=None, description="Optional status string associated with the event"
    )
    agent_role: str | None = Field(
        default=None, description="Role identifier of the agent that emitted this event"
    )
    tool_name: str | None = Field(
        default=None,
        description="Name of the tool that was called or returned a result",
    )
    tool_arguments: dict[str, Any] | None = Field(
        default=None, description="Arguments passed to the tool call"
    )
    tool_result: dict[str, Any] | None = Field(
        default=None, description="Structured result returned by the tool"
    )
    handoff_source_role: str | None = Field(
        default=None, description="Role of the agent that initiated the handoff"
    )
    handoff_target_role: str | None = Field(
        default=None, description="Role of the agent that received the handoff"
    )
    post_processor_key: str | None = Field(
        default=None,
        description="Key identifying the post-processor that emitted this event",
    )
    message: str | None = Field(
        default=None, description="Optional human-readable event detail"
    )


class RunEventResponse(BaseModel):
    """Serialized run event for auditing and tests."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Database ID of the event")
    run_id: int = Field(description="ID of the run this event belongs to")
    event_type: RunEventType = Field(description="Type of workflow event")
    status: str | None = Field(
        description="Optional status string recorded with the event"
    )
    agent_role: str | None = Field(
        description="Role of the agent that emitted this event"
    )
    tool_name: str | None = Field(description="Name of the tool involved in this event")
    tool_arguments: dict[str, Any] | None = Field(
        description="Arguments passed to the tool call"
    )
    tool_result: dict[str, Any] | None = Field(
        description="Structured result returned by the tool"
    )
    handoff_source_role: str | None = Field(
        description="Role of the agent that initiated the handoff"
    )
    handoff_target_role: str | None = Field(
        description="Role of the agent that received the handoff"
    )
    post_processor_key: str | None = Field(
        description="Key of the post-processor that emitted this event"
    )
    message: str | None = Field(description="Optional human-readable event detail")
    created_at: datetime = Field(description="Timestamp when the event was recorded")
