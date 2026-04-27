"""Protected endpoints for creating and managing demo runs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi import Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_access_token
from app.core.config import get_settings
from app.db.session import get_db_session
from app.schemas.run_events import RunEventResponse
from app.schemas.runs import (
    RunCreateRequest,
    RunListResponse,
    RunResponse,
    RunSubmitRequest,
    RunUpdateRequest,
)
from app.services.run_events import serialize_run_event
from app.services.runs import (
    create_run,
    get_run_or_404,
    ingest_run_draft,
    list_runs,
    serialize_run,
    serialize_run_list,
    submit_run,
    update_run_draft,
)
from app.services.workflow_executor import execute_run_workflow, get_run_events

router = APIRouter(
    prefix="/api/runs",
    tags=["runs"],
    dependencies=[Depends(get_current_access_token)],
)


@router.get("", response_model=RunListResponse)
def list_runs_route(db: Session = Depends(get_db_session)) -> RunListResponse:
    """Return newest-first run history for the protected demo shell."""
    return serialize_run_list(list_runs(db))


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def create_run_route(
    payload: RunCreateRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Create a new draft run."""
    return serialize_run(create_run(db, payload))


@router.get("/{run_id}", response_model=RunResponse)
def get_run_route(run_id: int, db: Session = Depends(get_db_session)) -> RunResponse:
    """Return one persisted run."""
    return serialize_run(get_run_or_404(db, run_id))


@router.put("/{run_id}", response_model=RunResponse)
def update_run_route(
    run_id: int,
    payload: RunUpdateRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Update the editable draft fields of a run."""
    run = get_run_or_404(db, run_id)
    return serialize_run(update_run_draft(db, run, payload))


@router.post("/{run_id}/ingest", response_model=RunResponse)
async def ingest_run_route(
    run_id: int,
    title: Annotated[str | None, Form()] = None,
    input_text: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile], File()] = [],
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Normalize pasted text and uploads for a draft run."""
    run = get_run_or_404(db, run_id)
    updated = await ingest_run_draft(
        db,
        run,
        title=title,
        pasted_text=input_text,
        files=files,
    )
    return serialize_run(updated)


@router.post("/{run_id}/submit", response_model=RunResponse)
async def submit_run_route(
    run_id: int,
    request: Request,
    payload: RunSubmitRequest | None = None,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Submit and synchronously execute a run through the bounded workflow."""
    run = get_run_or_404(db, run_id)
    submitted = submit_run(db, run, payload)
    executed = await execute_run_workflow(
        db,
        submitted,
        request.app.state.workflow_registry,
        get_settings(),
    )
    return serialize_run(executed)


@router.post("/{run_id}/execute", response_model=RunResponse)
async def execute_run_route(
    run_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Execute an existing draft/submitted/failed run."""
    run = get_run_or_404(db, run_id)
    executed = await execute_run_workflow(
        db,
        run,
        request.app.state.workflow_registry,
        get_settings(),
    )
    return serialize_run(executed)


@router.get("/{run_id}/events", response_model=list[RunEventResponse])
def list_run_events_route(
    run_id: int,
    db: Session = Depends(get_db_session),
) -> list[RunEventResponse]:
    """Return structured execution events for a run."""
    run = get_run_or_404(db, run_id)
    return [serialize_run_event(event) for event in get_run_events(db, run.id)]
