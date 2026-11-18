"""Execution leases and durable step checkpoints for workflow runs.

Only one executor may own a run at a time. Ownership is a lease stored on the
``runs`` row (an opaque owner token plus an expiry timestamp) and is acquired
with a conditional ``UPDATE`` so it works across processes on PostgreSQL and
Oracle without advisory locks. A background thread renews the lease while the
executor is alive, so one slow tool, model, post-processor, or notification
call never lets the lease lapse. Every durable write made by the executor is
fenced by the owner token, so an executor that lost its lease cannot commit.

Completed steps are journaled in ``run_execution_steps`` together with their
run events and any run-column updates in a single transaction. A resumed
executor replays the journal instead of repeating completed work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
import threading
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import Connection, Engine, and_, delete, or_, update
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.models.run import Run, RunStatus
from app.models.run_execution_step import RunExecutionStep
from app.schemas.run_events import RunEventPayload
from app.services.run_events import build_run_event

logger = logging.getLogger(__name__)

RUN_NOT_EXECUTABLE_DETAIL = "Only draft, submitted, or failed runs can be executed."
RUN_ALREADY_EXECUTING_DETAIL = "This run is already being executed."

_FRESH_STATUSES = {
    RunStatus.DRAFT.value,
    RunStatus.SUBMITTED.value,
    RunStatus.FAILED.value,
}


class ExecutionLeaseLostError(RuntimeError):
    """Raised when an executor no longer owns the run it is executing."""


def utcnow() -> datetime:
    """Return the current UTC time used for lease bookkeeping."""
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def run_execution_conflict() -> HTTPException:
    """Return the conflict raised while another executor owns a run."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=RUN_ALREADY_EXECUTING_DETAIL,
    )


@dataclass
class RunExecutionLease:
    """Execution ownership of one run, renewed by a heartbeat thread."""

    run_id: int
    token: str
    lease_seconds: float
    resumed: bool
    engine: Engine
    lost: threading.Event = field(default_factory=threading.Event)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    @property
    def heartbeat_interval_seconds(self) -> float:
        """Renew several times per lease so one missed renewal is harmless."""
        return max(self.lease_seconds / 3, 0.05)

    def renewal_values(self) -> dict[str, Any]:
        """Return column values that extend the lease without touching updated_at."""
        return {
            "execution_lease_expires_at": utcnow()
            + timedelta(seconds=self.lease_seconds),
            "updated_at": Run.updated_at,
        }

    def owned_clause(self) -> Any:
        """Return the SQL predicate matching this lease's owned run row."""
        return and_(Run.id == self.run_id, Run.execution_owner_token == self.token)

    def start_heartbeat(self) -> None:
        """Start renewing the lease in a background thread."""
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"run-{self.run_id}-lease",
            daemon=True,
        )
        self._thread.start()

    def stop_heartbeat(self) -> None:
        """Stop renewing the lease and wait for the heartbeat thread."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def ensure_owned(self) -> None:
        """Raise when the heartbeat observed that ownership was lost."""
        if self.lost.is_set():
            raise ExecutionLeaseLostError(
                f"Execution lease for run {self.run_id} was lost."
            )

    def fence(self, db: Session) -> None:
        """Renew the lease inside ``db``'s transaction or fail if not owned.

        The row lock taken by this update is held until the caller commits, so
        no other executor can take over between the fence and the commit.
        """
        result = db.execute(
            update(Run)
            .where(self.owned_clause())
            .values(**self.renewal_values())
            .execution_options(synchronize_session=False)
        )
        if _rowcount(result) != 1:
            db.rollback()
            self.lost.set()
            raise ExecutionLeaseLostError(
                f"Execution lease for run {self.run_id} was lost."
            )

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_interval_seconds):
            try:
                with self.engine.begin() as connection:
                    result = connection.execute(
                        update(Run)
                        .where(self.owned_clause())
                        .values(**self.renewal_values())
                    )
                if _rowcount(result) != 1:
                    self.lost.set()
                    log_event(
                        logger,
                        "run_execution_lease_lost",
                        level=logging.WARNING,
                        run_id=self.run_id,
                    )
                    return
            except Exception as exc:
                log_event(
                    logger,
                    "run_execution_lease_renewal_failed",
                    level=logging.WARNING,
                    run_id=self.run_id,
                    error=str(exc),
                )


def acquire_run_execution(
    db: Session, run: Run, lease_seconds: float
) -> RunExecutionLease:
    """Take execution ownership of ``run`` or raise HTTP 409.

    Draft, submitted, and failed runs start a fresh execution and discard any
    earlier checkpoints. Processing runs whose lease has lapsed are resumed
    from their checkpoints. Processing runs with a live lease and completed
    runs are rejected.
    """
    db.refresh(run)
    observed_status = run.status
    now = utcnow()
    values: dict[str, Any] = {
        "execution_owner_token": uuid4().hex,
        "execution_lease_expires_at": now + timedelta(seconds=lease_seconds),
    }
    if observed_status in _FRESH_STATUSES:
        resumed = False
        condition = Run.status == observed_status
        values.update(
            status=RunStatus.PROCESSING.value,
            failed_at=None,
            failure_message=None,
            failure_internal_reason=None,
        )
    elif observed_status == RunStatus.PROCESSING.value:
        expires_at = run.execution_lease_expires_at
        if expires_at is not None and _as_utc(expires_at) > now:
            raise run_execution_conflict()
        resumed = True
        condition = and_(
            Run.status == RunStatus.PROCESSING.value,
            or_(
                Run.execution_lease_expires_at.is_(None),
                Run.execution_lease_expires_at <= now,
            ),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=RUN_NOT_EXECUTABLE_DETAIL,
        )

    result = db.execute(
        update(Run)
        .where(Run.id == run.id, condition)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if _rowcount(result) != 1:
        db.rollback()
        db.refresh(run)
        if run.status in _FRESH_STATUSES | {RunStatus.PROCESSING.value}:
            raise run_execution_conflict()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=RUN_NOT_EXECUTABLE_DETAIL,
        )
    if not resumed:
        db.execute(delete(RunExecutionStep).where(RunExecutionStep.run_id == run.id))
    db.commit()
    db.refresh(run)

    bind = db.get_bind()
    engine = bind.engine if isinstance(bind, Connection) else bind
    lease = RunExecutionLease(
        run_id=run.id,
        token=values["execution_owner_token"],
        lease_seconds=lease_seconds,
        resumed=resumed,
        engine=engine,
    )
    lease.start_heartbeat()
    return lease


class RunExecutionJournal:
    """Durable, lease-fenced checkpoint journal for one run execution.

    Steps are identified by their ordinal position plus a descriptive label.
    Executors are deterministic, so a resumed execution reaches the same keys
    in the same order and can reuse outputs of steps that already completed.
    """

    def __init__(self, db: Session, run: Run, lease: RunExecutionLease) -> None:
        self.db = db
        self.run = run
        self.lease = lease
        self._ordinal = 0
        self._pending_events: list[RunEventPayload] = []
        self._completed: dict[str, str | None] = {
            step.step_key: step.output_serialized
            for step in db.query(RunExecutionStep)
            .filter(RunExecutionStep.run_id == run.id)
            .all()
        }

    @property
    def completed_keys(self) -> list[str]:
        """Return keys of steps completed so far in this execution."""
        return list(self._completed)

    def begin(self, label: str) -> str:
        """Allocate the key of the next step and verify ownership."""
        self.lease.ensure_owned()
        self._ordinal += 1
        self._pending_events = []
        return f"{self._ordinal:03d}:{label}"[:255]

    def is_completed(self, key: str) -> bool:
        """Return whether ``key`` was durably completed by an earlier executor."""
        return key in self._completed

    def output(self, key: str) -> str | None:
        """Return the serialized output of a completed step."""
        return self._completed[key]

    def emit(self, payload: RunEventPayload) -> None:
        """Buffer an event so it is committed atomically with its step."""
        self._pending_events.append(payload)

    def complete(self, key: str, output: str | None = None) -> None:
        """Commit buffered events, pending run updates, and the checkpoint."""
        self.lease.ensure_owned()
        self.lease.fence(self.db)
        for payload in self._pending_events:
            self.db.add(build_run_event(self.run.id, payload))
        self.db.add(
            RunExecutionStep(run_id=self.run.id, step_key=key, output_serialized=output)
        )
        self.db.add(self.run)
        self.db.commit()
        self._pending_events = []
        self._completed[key] = output


def finish_run_execution(
    db: Session, lease: RunExecutionLease, values: dict[str, Any]
) -> None:
    """Apply final run values and release the lease in one fenced update."""
    result = db.execute(
        update(Run)
        .where(lease.owned_clause())
        .values(
            execution_owner_token=None,
            execution_lease_expires_at=None,
            **values,
        )
        .execution_options(synchronize_session=False)
    )
    if _rowcount(result) != 1:
        db.rollback()
        lease.lost.set()
        raise ExecutionLeaseLostError(
            f"Execution lease for run {lease.run_id} was lost."
        )


def _rowcount(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)
