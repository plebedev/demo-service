"""Minimal service helpers for demo run persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.run import Run, RunStatus
from app.schemas.runs import RunCreateRequest, RunSubmitRequest, RunUpdateRequest


def create_run(db: Session, payload: RunCreateRequest) -> Run:
    """Persist a newly created draft run."""
    run = Run(
        status=RunStatus.DRAFT.value,
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
    run.input_metadata_json = payload.input_metadata_json
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def submit_run(db: Session, run: Run, payload: RunSubmitRequest | None = None) -> Run:
    """Move a run into the submitted state until processing exists."""
    if payload is not None:
        run.title = cast(Any, _normalize_title(payload.title))
        run.input_text = cast(Any, _normalize_text(payload.input_text))
        run.input_metadata_json = payload.input_metadata_json

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
