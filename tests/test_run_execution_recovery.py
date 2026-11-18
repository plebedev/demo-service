"""Tests for run execution leases, interruption recovery, and concurrency."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any

from fastapi import HTTPException
import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import Run, RunEvent, RunExecutionStep, SmsMessage
from app.schemas.runs import NotificationPreferenceRequest, RunCreateRequest
from app.services.notifications import capture_notification_preference
from app.services.run_execution import (
    RUN_ALREADY_EXECUTING_DETAIL,
    RunExecutionJournal,
    acquire_run_execution,
)
from app.services.runs import create_run
from app.services.tool_registry import ToolRegistry
from app.services.workflow_executor import execute_run_workflow
from app.workflows.loader import (
    WorkflowAgentRuntime,
    WorkflowRegistry,
    load_workflow_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPT = REPO_ROOT / "tests" / "run_execution_worker.py"
LOCAL_SLM_OUTPUT = (
    '{"title":"Kitchen Remodel Planning",'
    '"summary":"Plan the kitchen remodel.",'
    '"key_points":["Cabinets may be white oak."],'
    '"open_questions":["Is a permit required?"],'
    '"risks":["Budget may creep."],'
    '"next_actions":["Review tile samples."]}'
)
NOTES = "Need legal summary\nDecision approved\nBudget risk is real\nTodo: owner"
WORKFLOW_KEYS = ["messy-notes-v1", "messy-notes-local-slm"]


class SimulatedCrash(BaseException):
    """Abrupt executor death that bypasses normal failure handling."""


class FakeAgent:
    """Model stand-in that records calls and never contacts a provider."""

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.calls = 0
        self.delay_seconds = delay_seconds
        self.started = threading.Event()

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        self.calls += 1
        self.started.set()
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return type("Result", (), {"output": LOCAL_SLM_OUTPUT})()


def access_headers(client, code: str) -> dict[str, str]:
    """Create and redeem a messy-notes invitation code."""
    created = client.post(
        "/api/internal/admin/invitations",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"code": code, "label": "messy-notes"},
    )
    assert created.status_code == 201
    redeem = client.post("/api/access/redeem", json={"code": code})
    assert redeem.status_code == 200
    return {"Authorization": f"Bearer {redeem.json()['access_token']}"}


def build_registry(
    workflow_key: str, agent: FakeAgent | None = None
) -> WorkflowRegistry:
    """Load the real workflow registry, swapping in a fake local model."""
    registry = load_workflow_registry(get_settings())
    if workflow_key == "messy-notes-local-slm":
        workflow = registry.get_workflow(workflow_key)
        runtime = workflow.agents["local_brief_writer"]
        workflow.agents["local_brief_writer"] = WorkflowAgentRuntime(
            config=runtime.config,
            system_prompt=runtime.system_prompt,
            agent=agent or FakeAgent(),  # type: ignore[arg-type]
        )
    return registry


def lease_settings(seconds: float) -> Settings:
    """Return test settings with a short execution lease."""
    return get_settings().model_copy(
        update={"workflow_execution_lease_seconds": seconds}
    )


def new_run(
    db: Session,
    workflow_key: str,
    *,
    wants_sms: bool = False,
    title: str = "Recovery run",
) -> Run:
    """Create a run for ``workflow_key`` with deterministic notes."""
    run = create_run(db, RunCreateRequest(title=title, input_text=NOTES))
    run.workflow_key = workflow_key
    db.add(run)
    db.commit()
    if wants_sms:
        capture_notification_preference(
            db,
            run,
            NotificationPreferenceRequest(
                wants_sms=True, phone_number="(415) 555-0134"
            ),
        )
    db.refresh(run)
    return run


def run_to_completion(
    session_factory: sessionmaker[Session],
    run_id: int,
    registry: WorkflowRegistry,
    settings: Settings | None = None,
) -> Run:
    """Execute a run in a fresh session, like a new request or process."""
    session = session_factory()
    try:
        run = session.get(Run, run_id)
        assert run is not None
        return asyncio.run(
            execute_run_workflow(session, run, registry, settings or get_settings())
        )
    finally:
        session.close()


def event_signatures(db: Session, run_id: int) -> list[tuple[Any, ...]]:
    """Return comparable event content in API order."""
    db.expire_all()
    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.id.asc())
        .all()
    )
    return [
        (
            event.event_type,
            event.status,
            event.agent_role,
            event.tool_name,
            event.tool_arguments_serialized,
            event.tool_result_serialized,
            event.handoff_source_role,
            event.handoff_target_role,
            event.post_processor_key,
            event.message,
        )
        for event in events
    ]


def expire_lease(db: Session, run_id: int) -> None:
    """Make a run's execution lease look abandoned."""
    db.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(execution_lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()


@pytest.fixture()
def tool_calls(monkeypatch) -> Counter[str]:
    """Count real deterministic tool executions by tool name."""
    calls: Counter[str] = Counter()
    original = ToolRegistry.execute

    def counting_execute(self, name, payload):
        calls[name] += 1
        return original(self, name, payload)

    monkeypatch.setattr(ToolRegistry, "execute", counting_execute)
    return calls


@pytest.fixture()
def sms_sends(monkeypatch) -> list[int]:
    """Record completion SMS sends without contacting Twilio."""
    sent: list[int] = []

    def fake_send(settings, *, to_phone_number: str, body: str):
        del settings, to_phone_number
        sent.append(len(body))
        return type("Result", (), {"provider_message_sid": "SM1", "status": "sent"})()

    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)
    return sent


def test_lease_setting_defaults_to_sixty_seconds_and_reads_environment(
    monkeypatch,
) -> None:
    base = {"DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1/db_test"}
    monkeypatch.delenv("WORKFLOW_EXECUTION_LEASE_SECONDS", raising=False)
    assert Settings.model_validate(base).workflow_execution_lease_seconds == 60

    monkeypatch.setenv("WORKFLOW_EXECUTION_LEASE_SECONDS", "15")
    assert Settings.model_validate(base).workflow_execution_lease_seconds == 15


@pytest.mark.parametrize("workflow_key", WORKFLOW_KEYS)
def test_completed_execution_releases_lease_and_checkpoints_steps(
    db_session, session_factory, workflow_key
) -> None:
    run = new_run(db_session, workflow_key)

    run_to_completion(session_factory, run.id, build_registry(workflow_key))

    db_session.refresh(run)
    assert run.status == "completed"
    assert run.execution_owner_token is None
    assert run.execution_lease_expires_at is None
    step_keys = [
        step.step_key
        for step in db_session.query(RunExecutionStep)
        .filter(RunExecutionStep.run_id == run.id)
        .order_by(RunExecutionStep.id.asc())
    ]
    assert step_keys[0] == "001:run_execution_started"
    assert step_keys[-1].endswith(":completion_notification")
    assert any(":post_processor:" in key for key in step_keys)


@pytest.mark.parametrize("crash_phase", ["before_step", "before_commit"])
@pytest.mark.parametrize("workflow_key", WORKFLOW_KEYS)
def test_resume_after_crash_at_every_step_matches_uninterrupted_run(
    db_session,
    session_factory,
    monkeypatch,
    tool_calls,
    sms_sends,
    workflow_key,
    crash_phase,
) -> None:
    reference_agent = FakeAgent()
    reference = new_run(db_session, workflow_key, wants_sms=True)
    run_to_completion(
        session_factory, reference.id, build_registry(workflow_key, reference_agent)
    )
    expected_events = event_signatures(db_session, reference.id)
    db_session.refresh(reference)
    expected_brief = reference.output_brief_serialized
    expected_audit = reference.post_processor_results_serialized
    step_keys = [
        step.step_key
        for step in db_session.query(RunExecutionStep).filter(
            RunExecutionStep.run_id == reference.id
        )
    ]
    reference_tools = Counter(tool_calls)
    assert len(sms_sends) == 1
    assert reference_agent.calls == (1 if workflow_key != "messy-notes-v1" else 0)

    crash_at: dict[str, str | None] = {"key": None}
    original_begin = RunExecutionJournal.begin
    original_complete = RunExecutionJournal.complete

    def crashing_begin(self, label):
        key = original_begin(self, label)
        if crash_phase == "before_step" and key == crash_at["key"]:
            crash_at["key"] = None
            raise SimulatedCrash(key)
        return key

    def crashing_complete(self, key, output=None):
        if crash_phase == "before_commit" and key == crash_at["key"]:
            crash_at["key"] = None
            raise SimulatedCrash(key)
        return original_complete(self, key, output)

    monkeypatch.setattr(RunExecutionJournal, "begin", crashing_begin)
    monkeypatch.setattr(RunExecutionJournal, "complete", crashing_complete)

    for crash_key in sorted(step_keys):
        tool_calls.clear()
        sms_sends.clear()
        agent = FakeAgent()
        registry = build_registry(workflow_key, agent)
        run = new_run(db_session, workflow_key, wants_sms=True)
        crash_at["key"] = crash_key

        with pytest.raises(SimulatedCrash):
            run_to_completion(session_factory, run.id, registry)

        db_session.refresh(run)
        assert run.status == "processing", crash_key
        assert run.execution_owner_token is not None
        expire_lease(db_session, run.id)

        resumed = run_to_completion(session_factory, run.id, registry)

        assert resumed.status == "completed", crash_key
        db_session.refresh(run)
        assert run.execution_owner_token is None
        assert run.output_brief_serialized == expected_brief
        assert run.post_processor_results_serialized == expected_audit
        assert event_signatures(db_session, run.id) == expected_events, crash_key
        assert len(sms_sends) == 1, crash_key
        assert db_session.query(SmsMessage).filter_by(run_id=run.id).count() == 1

        crashed_label = crash_key.split(":", 1)[1]
        repeated = (
            _tools_in_step(crashed_label) if crash_phase == "before_commit" else set()
        )
        for tool_name, count in reference_tools.items():
            expected = count * (2 if tool_name in repeated else 1)
            assert tool_calls[tool_name] == expected, (crash_key, tool_name)
        expected_model_calls = reference_agent.calls
        if crash_phase == "before_commit" and crashed_label.startswith("model:"):
            expected_model_calls += 1
        assert agent.calls == expected_model_calls, crash_key


def _tools_in_step(label: str) -> set[str]:
    if label.startswith("tool:"):
        return {label.rsplit(":", 1)[1]}
    if label.startswith("parallel:"):
        return {"extract_claims", "extract_decisions", "extract_action_items"}
    return set()


def test_execute_returns_conflict_while_lease_is_active_and_resumes_after_expiry(
    client, db_session, tool_calls
) -> None:
    headers = access_headers(client, "recovery-conflict")
    created = client.post(
        "/api/runs", headers=headers, json={"title": "Busy", "input_text": NOTES}
    )
    run_id = created.json()["id"]
    run = db_session.get(Run, run_id)
    assert run is not None
    run.status = "processing"
    run.execution_owner_token = "other-executor"
    run.execution_lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    db_session.add(run)
    db_session.commit()

    executing = client.post(f"/api/runs/{run_id}/execute", headers=headers)
    assert executing.status_code == 409
    assert executing.json()["detail"] == RUN_ALREADY_EXECUTING_DETAIL
    submitting = client.post(f"/api/runs/{run_id}/submit", headers=headers)
    assert submitting.status_code == 409
    assert submitting.json()["detail"] == "Only draft or failed runs can be submitted."
    assert sum(tool_calls.values()) == 0

    expire_lease(db_session, run_id)
    resumed = client.post(f"/api/runs/{run_id}/execute", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"

    completed_again = client.post(f"/api/runs/{run_id}/execute", headers=headers)
    assert completed_again.status_code == 409
    assert completed_again.json()["detail"] == (
        "Only draft, submitted, or failed runs can be executed."
    )


def test_concurrent_acquisition_allows_exactly_one_owner(
    db_session, session_factory
) -> None:
    run = new_run(db_session, "messy-notes-v1")
    barrier = threading.Barrier(4)
    outcomes: list[str] = []
    lock = threading.Lock()

    def contend() -> None:
        session = session_factory()
        try:
            contender = session.get(Run, run.id)
            assert contender is not None
            barrier.wait()
            try:
                lease = acquire_run_execution(session, contender, 30)
            except HTTPException as exc:
                with lock:
                    outcomes.append(f"{exc.status_code}:{exc.detail}")
                return
            lease.stop_heartbeat()
            with lock:
                outcomes.append("owner")
        finally:
            session.close()

    threads = [threading.Thread(target=contend) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("owner") == 1
    assert outcomes.count(f"409:{RUN_ALREADY_EXECUTING_DETAIL}") == 3


def test_stale_executor_cannot_commit_after_takeover(
    db_session, session_factory
) -> None:
    run = new_run(db_session, "messy-notes-v1")
    stale_session = session_factory()
    try:
        stale_run = stale_session.get(Run, run.id)
        assert stale_run is not None
        stale_lease = acquire_run_execution(stale_session, stale_run, 30)
        stale_lease.stop_heartbeat()
        expire_lease(db_session, run.id)

        new_session = session_factory()
        try:
            new_run_row = new_session.get(Run, run.id)
            assert new_run_row is not None
            new_lease = acquire_run_execution(new_session, new_run_row, 30)
            new_lease.stop_heartbeat()
            assert new_lease.resumed is True
        finally:
            new_session.close()

        journal = RunExecutionJournal(stale_session, stale_run, stale_lease)
        key = journal.begin("run_execution_started")
        with pytest.raises(Exception, match="lease"):
            journal.complete(key, "{}")
        assert db_session.query(RunExecutionStep).filter_by(run_id=run.id).count() == 0
    finally:
        stale_session.close()


@pytest.mark.parametrize(
    "slow_step", ["tool", "model", "post_processor", "notification"]
)
def test_live_executor_keeps_ownership_during_step_longer_than_lease(
    client, db_session, session_factory, monkeypatch, sms_sends, slow_step
) -> None:
    lease_seconds = 0.5
    slow_seconds = 1.8
    started = threading.Event()
    workflow_key = "messy-notes-local-slm" if slow_step == "model" else "messy-notes-v1"
    agent = FakeAgent(delay_seconds=slow_seconds)
    registry = build_registry(workflow_key, agent)

    if slow_step == "tool":
        original_execute = registry.tool_registry.execute

        def slow_execute(name, payload):
            if name == "find_duplicates":
                started.set()
                time.sleep(slow_seconds)
            return original_execute(name, payload)

        registry.tool_registry.execute = slow_execute  # type: ignore[method-assign]
    elif slow_step == "model":
        started = agent.started
    elif slow_step == "post_processor":
        from app.services import workflow_executor

        original_audit = workflow_executor._audit_tool_usage_and_handoffs

        def slow_audit(workflow, events):
            started.set()
            time.sleep(slow_seconds)
            return original_audit(workflow, events)

        monkeypatch.setattr(
            workflow_executor, "_audit_tool_usage_and_handoffs", slow_audit
        )
    else:

        def slow_send(settings, *, to_phone_number: str, body: str):
            del settings, to_phone_number, body
            started.set()
            time.sleep(slow_seconds)
            sms_sends.append(1)
            return type("Result", (), {"provider_message_sid": "S", "status": "sent"})()

        monkeypatch.setattr("app.services.notifications.send_sms", slow_send)

    headers = access_headers(client, f"recovery-slow-{slow_step}")
    created = client.post(
        "/api/runs", headers=headers, json={"title": "Slow", "input_text": NOTES}
    )
    run_id = created.json()["id"]
    run = db_session.get(Run, run_id)
    assert run is not None
    run.workflow_key = workflow_key
    db_session.add(run)
    db_session.commit()
    if slow_step == "notification":
        capture_notification_preference(
            db_session,
            run,
            NotificationPreferenceRequest(
                wants_sms=True, phone_number="(415) 555-0134"
            ),
        )

    errors: list[BaseException] = []

    def execute_in_background() -> None:
        try:
            run_to_completion(
                session_factory, run_id, registry, lease_settings(lease_seconds)
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    worker = threading.Thread(target=execute_in_background)
    worker.start()
    try:
        assert started.wait(10)
        time.sleep(lease_seconds * 2.5)
        conflict = client.post(f"/api/runs/{run_id}/execute", headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == RUN_ALREADY_EXECUTING_DETAIL
    finally:
        worker.join(30)

    assert not errors
    db_session.expire_all()
    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.execution_owner_token is None
    signatures = event_signatures(db_session, run_id)
    assert [sig[0] for sig in signatures].count("run_execution_started") == 1
    assert [sig[0] for sig in signatures].count("run_completed") == 1
    if slow_step == "notification":
        assert sms_sends == [1]


@pytest.fixture()
def worker_env(database_url: str) -> Iterator[Callable[[float], dict[str, str]]]:
    """Return an environment builder for worker subprocesses."""
    del database_url

    def build(lease_seconds: float) -> dict[str, str]:
        env = dict(os.environ)
        env["WORKFLOW_EXECUTION_LEASE_SECONDS"] = str(lease_seconds)
        env["PYTHONPATH"] = str(REPO_ROOT)
        return env

    yield build


def start_worker(env: dict[str, str], run_id: int, *args: str) -> subprocess.Popen[str]:
    """Start a worker process that executes ``run_id``."""
    return subprocess.Popen(
        [sys.executable, str(WORKER_SCRIPT), str(run_id), *args],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
    """Poll ``predicate`` until it is true or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_killed_worker_process_is_recovered_by_another_process(
    client, db_session, session_factory, tool_calls, worker_env, tmp_path
) -> None:
    headers = access_headers(client, "recovery-kill")
    reference = new_run(db_session, "messy-notes-v1", title="Killed")
    run_to_completion(session_factory, reference.id, build_registry("messy-notes-v1"))
    expected_events = event_signatures(db_session, reference.id)
    tool_calls.clear()

    created = client.post(
        "/api/runs", headers=headers, json={"title": "Killed", "input_text": NOTES}
    )
    run_id = created.json()["id"]
    marker = tmp_path / "blocked"
    worker = start_worker(
        worker_env(1.0),
        run_id,
        "--block-tool",
        "find_duplicates",
        "--block-seconds",
        "120",
        "--marker",
        str(marker),
    )
    try:
        assert wait_for(marker.exists, 60), (
            worker.stdout.read() if worker.stdout else ""
        )
        time.sleep(2.5)
        conflict = client.post(f"/api/runs/{run_id}/execute", headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == RUN_ALREADY_EXECUTING_DETAIL
    finally:
        worker.kill()
        worker.wait(10)

    def lease_expired() -> bool:
        db_session.expire_all()
        row = db_session.get(Run, run_id)
        assert row is not None
        expires_at = row.execution_lease_expires_at
        return expires_at is not None and expires_at < datetime.now(UTC)

    assert wait_for(lease_expired, 10)
    resumed = client.post(f"/api/runs/{run_id}/execute", headers=headers)

    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert dict(tool_calls) == {
        "find_duplicates": 1,
        "find_contradictions": 1,
        "format_brief": 1,
    }
    assert event_signatures(db_session, run_id) == expected_events
    api_events = client.get(f"/api/runs/{run_id}/events", headers=headers).json()
    assert [event["id"] for event in api_events] == sorted(
        event["id"] for event in api_events
    )
    tool_results = [
        event["tool_name"]
        for event in api_events
        if event["event_type"] == "tool_result"
    ]
    assert len(tool_results) == len(set(tool_results))


def test_concurrent_worker_processes_execute_run_once(db_session, worker_env) -> None:
    run = new_run(db_session, "messy-notes-v1")
    env = worker_env(1.0)
    workers = [
        start_worker(
            env,
            run.id,
            "--block-tool",
            "find_duplicates",
            "--block-seconds",
            "5",
        )
        for _ in range(2)
    ]
    outputs = []
    for worker in workers:
        stdout, _ = worker.communicate(timeout=120)
        outputs.append((worker.returncode, stdout))

    codes = sorted(code for code, _ in outputs)
    assert codes == [0, 3], outputs
    conflict_output = next(stdout for code, stdout in outputs if code == 3)
    assert RUN_ALREADY_EXECUTING_DETAIL in conflict_output
    db_session.refresh(run)
    assert run.status == "completed"
    signatures = event_signatures(db_session, run.id)
    assert [sig[0] for sig in signatures].count("run_execution_started") == 1
    tool_results = [sig[3] for sig in signatures if sig[0] == "tool_result"]
    assert len(tool_results) == len(set(tool_results))
