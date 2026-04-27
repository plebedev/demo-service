"""Pydantic schemas for persisted demo runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.run import RunStatus


class RunCreateRequest(BaseModel):
    """Request body for creating a new run."""

    title: str | None = Field(default=None, max_length=255)
    input_text: str | None = None


class RunUpdateRequest(BaseModel):
    """Request body for updating the editable draft fields of a run."""

    title: str | None = Field(default=None, max_length=255)
    input_text: str | None = None
    input_metadata_json: dict[str, Any] | None = None


class RunSubmitRequest(BaseModel):
    """Optional data accepted when a run is submitted."""

    title: str | None = Field(default=None, max_length=255)
    input_text: str | None = None
    input_metadata_json: dict[str, Any] | None = None


class RunResponse(BaseModel):
    """Serialized run record returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: RunStatus
    title: str | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    input_text: str | None
    input_metadata_json: dict[str, Any] | None
    output_brief_json: dict[str, Any] | None
    follow_up_count: int


class RunListResponse(BaseModel):
    """Simple list wrapper for newest-first run history."""

    runs: list[RunResponse]
