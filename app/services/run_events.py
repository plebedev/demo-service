"""Persistence helpers for structured workflow run events."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.run import Run
from app.models.run_event import RunEvent, RunEventType
from app.schemas.run_events import RunEventPayload, RunEventResponse


def record_run_event(
    db: Session,
    run: Run,
    payload: RunEventPayload,
) -> RunEvent:
    """Persist a structured run event for future audit and post-processing."""
    event = RunEvent(
        run_id=run.id,
        event_type=payload.event_type.value,
        agent_role=payload.agent_role,
        tool_name=payload.tool_name,
        tool_arguments_serialized=_serialize_json(payload.tool_arguments),
        tool_result_serialized=_serialize_json(payload.tool_result),
        handoff_source_role=payload.handoff_source_role,
        handoff_target_role=payload.handoff_target_role,
        post_processor_key=payload.post_processor_key,
        message=payload.message,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def serialize_run_event(event: RunEvent) -> RunEventResponse:
    """Deserialize stored JSON payloads back into the response schema."""
    return RunEventResponse(
        id=event.id,
        run_id=event.run_id,
        event_type=RunEventType(event.event_type),
        agent_role=event.agent_role,
        tool_name=event.tool_name,
        tool_arguments=_deserialize_json(event.tool_arguments_serialized),
        tool_result=_deserialize_json(event.tool_result_serialized),
        handoff_source_role=event.handoff_source_role,
        handoff_target_role=event.handoff_target_role,
        post_processor_key=event.post_processor_key,
        message=event.message,
        created_at=event.created_at,
    )


def _serialize_json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _deserialize_json(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("Run event JSON payload must decode to an object.")
    return payload
