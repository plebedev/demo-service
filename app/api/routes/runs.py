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
    FollowUpRequest,
    NotificationPreferenceRequest,
    RunCreateRequest,
    RunExecutionSummary,
    RunListResponse,
    RunResponse,
    SampleChaosApplyRequest,
    SampleChaosListResponse,
    SmsPhoneStatusRequest,
    SmsPhoneStatusResponse,
    RunSubmitRequest,
    RunUpdateRequest,
)
from app.services.follow_up import answer_follow_up
from app.services.notifications import (
    capture_notification_preference,
    get_sms_phone_status,
    maybe_send_completion_notification,
)
from app.services.run_events import serialize_run_event
from app.services.runs import (
    apply_sample_chaos_to_run,
    create_run,
    get_run_or_404,
    ingest_run_draft,
    list_runs,
    serialize_run,
    serialize_run_list,
    submit_run,
    update_run_draft,
)
from app.services.sample_chaos import list_sample_chaos_sets
from app.services.workflow_executor import (
    build_run_execution_summary,
    execute_run_workflow,
    get_run_events,
)

router = APIRouter(
    prefix="/api/runs",
    tags=["runs"],
    dependencies=[Depends(get_current_access_token)],
)


@router.get("", response_model=RunListResponse)
def list_runs_route(db: Session = Depends(get_db_session)) -> RunListResponse:
    """Return newest-first run history for the protected demo shell."""
    return serialize_run_list(list_runs(db), db)


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def create_run_route(
    payload: RunCreateRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Create a new draft run."""
    return serialize_run(create_run(db, payload), db)


@router.get("/samples", response_model=SampleChaosListResponse)
def list_sample_chaos_route() -> SampleChaosListResponse:
    """Return curated sample note sets for the demo."""
    return SampleChaosListResponse(samples=list_sample_chaos_sets())


@router.post("/sms-status", response_model=SmsPhoneStatusResponse)
def sms_phone_status_route(
    payload: SmsPhoneStatusRequest,
    db: Session = Depends(get_db_session),
) -> SmsPhoneStatusResponse:
    """Return phone validity and permanent opt-out status for the UI."""
    return get_sms_phone_status(db, payload.phone_number)


@router.get("/{run_id}", response_model=RunResponse)
def get_run_route(run_id: int, db: Session = Depends(get_db_session)) -> RunResponse:
    """Return one persisted run."""
    return serialize_run(get_run_or_404(db, run_id), db)


@router.put("/{run_id}", response_model=RunResponse)
def update_run_route(
    run_id: int,
    payload: RunUpdateRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Update the editable draft fields of a run."""
    run = get_run_or_404(db, run_id)
    return serialize_run(update_run_draft(db, run, payload), db)


@router.post("/{run_id}/sample", response_model=RunResponse)
def apply_sample_chaos_route(
    run_id: int,
    payload: SampleChaosApplyRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Load a curated sample chaos set into a draft run."""
    run = get_run_or_404(db, run_id)
    return serialize_run(apply_sample_chaos_to_run(db, run, payload.sample_key), db)


@router.post("/{run_id}/notification-preference", response_model=RunResponse)
def notification_preference_route(
    run_id: int,
    payload: NotificationPreferenceRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Capture optional future SMS completion notification preference."""
    run = get_run_or_404(db, run_id)
    return serialize_run(capture_notification_preference(db, run, payload), db)


@router.post("/{run_id}/follow-up", response_model=RunResponse)
def follow_up_route(
    run_id: int,
    payload: FollowUpRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    """Answer the one guarded follow-up question for a completed run."""
    run = get_run_or_404(db, run_id)
    return serialize_run(answer_follow_up(db, run, payload), db)


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
    return serialize_run(updated, db)


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
    maybe_send_completion_notification(db, executed, get_settings())
    return serialize_run(executed, db)


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
    maybe_send_completion_notification(db, executed, get_settings())
    return serialize_run(executed, db)


@router.get("/{run_id}/events", response_model=list[RunEventResponse])
def list_run_events_route(
    run_id: int,
    db: Session = Depends(get_db_session),
) -> list[RunEventResponse]:
    """Return structured execution events for a run."""
    run = get_run_or_404(db, run_id)
    return [serialize_run_event(event) for event in get_run_events(db, run.id)]


@router.get("/{run_id}/summary", response_model=RunExecutionSummary)
def get_run_execution_summary_route(
    run_id: int,
    db: Session = Depends(get_db_session),
) -> RunExecutionSummary:
    """Return a compact execution summary for demos and debugging."""
    run = get_run_or_404(db, run_id)
    return build_run_execution_summary(db, run)
