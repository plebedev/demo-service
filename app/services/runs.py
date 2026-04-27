"""Minimal service helpers for demo run persistence."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, TypeVar, cast

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.run import Run, RunStatus
from app.schemas.runs import (
    RunCreateRequest,
    RunIngestionSummary,
    RunInputMetadata,
    RunListResponse,
    RunResponse,
    RunSubmitRequest,
    RunUpdateRequest,
    UploadedRunFile,
)
from app.services.run_ingestion import ingest_run_input

ModelT = TypeVar("ModelT", bound=BaseModel)


def create_run(db: Session, payload: RunCreateRequest) -> Run:
    """Persist a newly created draft run."""
    run = Run(
        status=RunStatus.DRAFT.value,
        workflow_key=get_settings().default_workflow_key,
        title=cast(Any, _normalize_title(payload.title)),
        input_text=cast(Any, _normalize_text(payload.input_text)),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run_or_404(db: Session, run_id: int) -> Run:
    """Load one run by id or raise a 404."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )
    return run


def list_runs(db: Session) -> list[Run]:
    """Return newest-first run history."""
    return db.query(Run).order_by(Run.created_at.desc(), Run.id.desc()).all()


def update_run_draft(db: Session, run: Run, payload: RunUpdateRequest) -> Run:
    """Update editable fields for a run without changing its lifecycle state."""
    run.title = cast(Any, _normalize_title(payload.title))
    run.input_text = cast(Any, _normalize_text(payload.input_text))
    run.input_metadata_serialized = cast(
        Any, _serialize_model(payload.input_metadata_json)
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


async def ingest_run_draft(
    db: Session,
    run: Run,
    *,
    title: str | None,
    pasted_text: str | None,
    files: list[Any],
) -> Run:
    """Persist normalized run input while the run is still editable."""
    if run.status not in {RunStatus.DRAFT.value, RunStatus.FAILED.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft or failed runs can be updated.",
        )

    ingestion = await ingest_run_input(
        settings=get_settings(),
        pasted_text=pasted_text,
        files=files,
    )
    run.title = cast(Any, _normalize_title(title))
    run.input_text = cast(Any, ingestion.raw_pasted_text)
    run.normalized_input_text = cast(Any, ingestion.normalized_input_text)
    run.input_metadata_serialized = cast(
        Any, _serialize_model(ingestion.input_metadata_json)
    )
    run.uploaded_files_serialized = cast(
        Any, _serialize_list_model(ingestion.uploaded_files_json)
    )
    run.ingestion_summary_serialized = cast(
        Any, _serialize_model(ingestion.ingestion_summary_json)
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def submit_run(db: Session, run: Run, payload: RunSubmitRequest | None = None) -> Run:
    """Move a run into the submitted state until processing exists."""
    if payload is not None:
        if payload.title is not None:
            run.title = cast(Any, _normalize_title(payload.title))
        if payload.input_text is not None:
            run.input_text = cast(Any, _normalize_text(payload.input_text))
        if payload.input_metadata_json is not None:
            run.input_metadata_serialized = cast(
                Any, _serialize_model(payload.input_metadata_json)
            )

    if run.status not in {RunStatus.DRAFT.value, RunStatus.FAILED.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft or failed runs can be submitted.",
        )

    run.status = RunStatus.SUBMITTED.value
    run.submitted_at = datetime.now(UTC)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def serialize_run(run: Run) -> RunResponse:
    """Convert one persisted ORM run into the API response shape."""
    return RunResponse(
        id=run.id,
        status=RunStatus(run.status),
        workflow_key=run.workflow_key,
        title=run.title,
        created_at=run.created_at,
        updated_at=run.updated_at,
        submitted_at=run.submitted_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        input_text=run.input_text,
        normalized_input_text=run.normalized_input_text,
        input_metadata_json=_deserialize_model(
            run.input_metadata_serialized, RunInputMetadata
        ),
        uploaded_files_json=_deserialize_list_model(
            run.uploaded_files_serialized, UploadedRunFile
        ),
        ingestion_summary_json=_deserialize_model(
            run.ingestion_summary_serialized, RunIngestionSummary
        ),
        output_brief_json=_deserialize_json_object(run.output_brief_serialized),
        follow_up_count=run.follow_up_count,
    )


def serialize_run_list(runs: list[Run]) -> RunListResponse:
    """Convert a run list to its API wrapper."""
    return RunListResponse(runs=[serialize_run(run) for run in runs])


def _normalize_title(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _serialize_model(value: Any) -> str | None:
    if value is None:
        return None
    return cast(str, value.model_dump_json())


def _serialize_list_model(values: list[Any] | None) -> str | None:
    if values is None:
        return None
    return json.dumps([value.model_dump(mode="json") for value in values])


def _deserialize_model(
    serialized: str | None, model_type: type[ModelT]
) -> ModelT | None:
    if serialized is None:
        return None
    return model_type.model_validate_json(serialized)


def _deserialize_list_model(
    serialized: str | None, item_type: type[ModelT]
) -> list[ModelT] | None:
    if serialized is None:
        return None
    payload = json.loads(serialized)
    return [item_type.model_validate(item) for item in payload]


def _deserialize_json_object(serialized: str | None) -> dict[str, object] | None:
    if serialized is None:
        return None
    payload = json.loads(serialized)
    if not isinstance(payload, dict):
        raise ValueError("Serialized JSON object payload must decode to a dictionary.")
    return cast(dict[str, object], payload)
