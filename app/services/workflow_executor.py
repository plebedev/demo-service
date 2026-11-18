"""Bounded, recoverable runtime execution for the messy-notes workflows."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from typing import Any, cast

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic_ai.usage import UsageLimits
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.models.run import Run, RunStatus
from app.models.run_event import RunEvent, RunEventType
from app.schemas.run_events import RunEventPayload
from app.schemas.runs import RunExecutionSummary
from app.services.notifications import (
    completion_notification_recorded,
    send_completion_notification,
)
from app.services.run_events import build_run_event
from app.services.run_execution import (
    ExecutionLeaseLostError,
    RunExecutionJournal,
    RunExecutionLease,
    acquire_run_execution,
    finish_run_execution,
    run_execution_conflict,
)
from app.workflows.config_models import AgentWorkflowConfig
from app.workflows.loader import WorkflowRegistry, WorkflowRuntime
from app.workflows.tools import (
    BriefInput,
    BriefOutput,
    BriefSection,
    ContradictionFindingsOutput,
    DuplicateFindingsOutput,
    ExtractedItemsOutput,
    ReconciliationInput,
    SectionsInput,
    SectionsOutput,
    SectionsToolInput,
    TextToolInput,
    WorkflowAgentDeps,
)

logger = logging.getLogger(__name__)


class WorkflowExecutionError(RuntimeError):
    """Raised when a bounded workflow cannot proceed."""


class LocalSlmProjectBrief(BaseModel):
    """Strict JSON shape emitted by the locally fine-tuned messy-brief SLM."""

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    key_points: list[str]
    open_questions: list[str]
    risks: list[str]
    next_actions: list[str]


class _RunInputs(BaseModel):
    """Run inputs captured when execution starts and restored on resume."""

    title: str | None
    source_text: str


@dataclass
class _ExecutionContext:
    db: Session
    run: Run
    journal: RunExecutionJournal
    registry: WorkflowRegistry
    workflow: WorkflowRuntime
    settings: Settings
    inputs: _RunInputs | None = None

    def require_inputs(self) -> _RunInputs:
        if self.inputs is None:
            raise WorkflowExecutionError("Run execution inputs were not captured.")
        return self.inputs


async def execute_run_workflow(
    db: Session,
    run: Run,
    registry: WorkflowRegistry,
    settings: Settings,
) -> Run:
    """Execute or resume one run synchronously while holding its lease.

    Draft, submitted, and failed runs start a fresh execution. A processing
    run whose executor stopped renewing its lease resumes after its last
    durably completed step. A run with a live executor is rejected with 409.
    """
    lease = acquire_run_execution(db, run, settings.workflow_execution_lease_seconds)
    try:
        return await _execute_owned_run(db, run, registry, settings, lease)
    finally:
        lease.stop_heartbeat()


async def _execute_owned_run(
    db: Session,
    run: Run,
    registry: WorkflowRegistry,
    settings: Settings,
    lease: RunExecutionLease,
) -> Run:
    try:
        journal = RunExecutionJournal(db, run, lease)
        workflow = registry.get_workflow(run.workflow_key)
        log_event(
            logger,
            "run_execution_resumed" if lease.resumed else "run_execution_started",
            run_id=run.id,
            workflow_key=workflow.config.key,
            completed_steps=len(journal.completed_keys),
        )
        ctx = _ExecutionContext(
            db=db,
            run=run,
            journal=journal,
            registry=registry,
            workflow=workflow,
            settings=settings,
        )
        ctx.inputs = _execution_started(ctx)

        await _execute_messy_notes(ctx)

        _run_completed(ctx)
        _run_post_processors(ctx)
        _completion_notification(ctx)

        finish_run_execution(
            db,
            lease,
            {
                "status": RunStatus.COMPLETED.value,
                "follow_up_count": func.coalesce(Run.follow_up_count, 0),
            },
        )
        db.commit()
        db.refresh(run)
        log_event(
            logger,
            "run_execution_completed",
            run_id=run.id,
            workflow_key=workflow.config.key,
        )
        return run
    except ExecutionLeaseLostError as exc:
        db.rollback()
        log_event(
            logger,
            "run_execution_lease_lost",
            level=logging.WARNING,
            run_id=run.id,
            workflow_key=run.workflow_key,
        )
        raise run_execution_conflict() from exc
    except Exception as exc:
        _record_failure(db, run, lease, exc)
        if isinstance(exc, HTTPException):
            raise
        raise WorkflowExecutionError(str(exc)) from exc


def _record_failure(
    db: Session, run: Run, lease: RunExecutionLease, exc: Exception
) -> None:
    db.rollback()
    failure_message = "The run failed during bounded workflow execution."
    try:
        finish_run_execution(
            db,
            lease,
            {
                "status": RunStatus.FAILED.value,
                "failed_at": datetime.now(UTC),
                "failure_message": failure_message,
                "failure_internal_reason": str(exc),
            },
        )
        db.add(
            build_run_event(
                run.id,
                RunEventPayload(
                    event_type=RunEventType.RUN_FAILED,
                    status=RunStatus.FAILED.value,
                    message=failure_message,
                    tool_result={"internal_reason": str(exc)[:500]},
                ),
            )
        )
        db.commit()
        db.refresh(run)
    except ExecutionLeaseLostError as lost:
        raise run_execution_conflict() from lost
    except Exception as write_exc:
        db.rollback()
        log_event(
            logger,
            "run_failure_record_failed",
            level=logging.ERROR,
            run_id=run.id,
            error=str(write_exc),
        )
    log_event(
        logger,
        "run_execution_failed",
        level=logging.ERROR,
        run_id=run.id,
        workflow_key=run.workflow_key,
        internal_reason=str(exc),
    )


def _execution_started(ctx: _ExecutionContext) -> _RunInputs:
    key = ctx.journal.begin("run_execution_started")
    if ctx.journal.is_completed(key):
        return _RunInputs.model_validate_json(_stored_output(ctx, key))
    inputs = _RunInputs(
        title=ctx.run.title,
        source_text=ctx.run.normalized_input_text or ctx.run.input_text or "",
    )
    _event(
        ctx,
        RunEventType.RUN_EXECUTION_STARTED,
        status=RunStatus.PROCESSING.value,
        message=f"Started workflow {ctx.workflow.config.key}.",
    )
    ctx.journal.complete(key, inputs.model_dump_json())
    return inputs


async def _execute_messy_notes(ctx: _ExecutionContext) -> None:
    workflow = ctx.workflow
    if workflow.config.key == "messy-notes-local-slm":
        await _execute_messy_notes_local_slm(ctx)
        return

    if workflow.config.key != "messy-notes-v1":
        raise WorkflowExecutionError(f"Unsupported workflow '{workflow.config.key}'.")

    inputs = ctx.require_inputs()
    orchestrator = workflow.config.starting_agent
    await _agent_started(ctx, orchestrator)
    normalized = cast(
        Any,
        _tool(
            ctx,
            orchestrator,
            "normalize_input",
            TextToolInput(text=inputs.source_text),
        ),
    )
    await _agent_finished(ctx, orchestrator)

    _handoff(ctx, orchestrator, "extractor")
    await _agent_started(ctx, "extractor")
    sections = cast(
        SectionsOutput,
        _tool(
            ctx,
            "extractor",
            "split_into_sections",
            SectionsInput(text=normalized.text),
        ),
    )
    extraction_input = SectionsToolInput(sections=sections.sections)
    claims, decisions, action_items = _run_extraction_parallel(ctx, extraction_input)
    await _agent_finished(ctx, "extractor")

    _handoff(ctx, "extractor", "reconciler")
    await _agent_started(ctx, "reconciler")
    reconciliation_input = ReconciliationInput(
        claims=claims.items,
        decisions=decisions.items,
        action_items=action_items.items,
    )
    duplicates = cast(
        DuplicateFindingsOutput,
        _tool(ctx, "reconciler", "find_duplicates", reconciliation_input),
    )
    contradictions = cast(
        ContradictionFindingsOutput,
        _tool(ctx, "reconciler", "find_contradictions", reconciliation_input),
    )
    await _agent_finished(ctx, "reconciler")

    _handoff(ctx, "reconciler", "brief_writer")
    await _agent_started(ctx, "brief_writer")
    brief = _tool(
        ctx,
        "brief_writer",
        "format_brief",
        BriefInput(
            title=inputs.title,
            claims=claims.items,
            decisions=decisions.items,
            action_items=action_items.items,
            duplicates=duplicates.duplicates,
            contradictions=contradictions.contradictions,
        ),
    )
    _persist_output_brief(ctx, brief)
    await _agent_finished(ctx, "brief_writer")


async def _execute_messy_notes_local_slm(ctx: _ExecutionContext) -> None:
    """Execute the local Ollama-backed single-model messy notes workflow."""
    workflow = ctx.workflow
    role = workflow.config.starting_agent
    await _agent_started(ctx, role, touch_agent=False)
    runtime = workflow.agents[role]
    if runtime.agent is None:
        raise WorkflowExecutionError(f"Workflow agent '{role}' is not executable.")

    source_text = ctx.require_inputs().source_text
    if not source_text.strip():
        raise WorkflowExecutionError("Cannot execute local SLM workflow without input.")

    key = ctx.journal.begin(f"model:{role}")
    if ctx.journal.is_completed(key):
        raw_output = _stored_output(ctx, key)
    else:
        prompt = (
            "Messy notes:\n"
            f"{source_text.strip()}\n\n"
            "Return only the strict JSON project brief."
        )
        result = await runtime.agent.run(
            prompt,
            deps=WorkflowAgentDeps(run=ctx.run, db=ctx.db),
            usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0),
        )
        raw_output = str(result.output)
        ctx.journal.complete(key, raw_output)
    project_brief = _parse_local_slm_project_brief(raw_output)
    brief = _local_project_brief_to_run_brief(project_brief)
    _persist_output_brief(ctx, brief)
    await _agent_finished(ctx, role)


def _persist_output_brief(ctx: _ExecutionContext, brief: BaseModel) -> None:
    key = ctx.journal.begin("persist_output_brief")
    if ctx.journal.is_completed(key):
        return
    ctx.run.output_brief_serialized = brief.model_dump_json()
    ctx.journal.complete(key)


def _run_extraction_parallel(
    ctx: _ExecutionContext,
    payload: SectionsToolInput,
) -> tuple[ExtractedItemsOutput, ExtractedItemsOutput, ExtractedItemsOutput]:
    registry = ctx.registry
    run = ctx.run
    extractor = _agent_config(ctx.workflow, "extractor")
    tool_names = ["extract_claims", "extract_decisions", "extract_action_items"]
    if extractor.parallel is None or not extractor.parallel.enabled:
        claims = cast(
            ExtractedItemsOutput,
            _tool(ctx, "extractor", "extract_claims", payload),
        )
        decisions = cast(
            ExtractedItemsOutput,
            _tool(ctx, "extractor", "extract_decisions", payload),
        )
        action_items = cast(
            ExtractedItemsOutput,
            _tool(ctx, "extractor", "extract_action_items", payload),
        )
        return claims, decisions, action_items

    key = ctx.journal.begin(f"parallel:extractor:{extractor.parallel.group}")
    if ctx.journal.is_completed(key):
        stored = json.loads(_stored_output(ctx, key))
        restored = [ExtractedItemsOutput.model_validate(stored[n]) for n in tool_names]
        return restored[0], restored[1], restored[2]

    for name in tool_names:
        _event(
            ctx,
            RunEventType.TOOL_CALLED,
            agent_role="extractor",
            tool_name=name,
            tool_arguments={"parallel_group": extractor.parallel.group},
            status=RunStatus.PROCESSING.value,
            message="Queued bounded extraction tool.",
        )
    with ThreadPoolExecutor(max_workers=len(tool_names)) as executor:
        futures = [
            executor.submit(registry.tool_registry.execute, name, payload)
            for name in tool_names
        ]
        try:
            results = [
                cast(ExtractedItemsOutput, future.result()) for future in futures
            ]
        except Exception:
            log_event(
                logger,
                "tool_execution_failed",
                level=logging.ERROR,
                run_id=run.id,
                agent_role="extractor",
                tool_name="parallel_extraction_group",
            )
            raise
    for name, result in zip(tool_names, results, strict=True):
        _event(
            ctx,
            RunEventType.TOOL_RESULT,
            agent_role="extractor",
            tool_name=name,
            tool_result={
                "item_count": len(result.items),
                "parallel_group": extractor.parallel.group,
            },
            status=RunStatus.PROCESSING.value,
            message="Completed bounded extraction tool.",
        )
    ctx.journal.complete(
        key,
        json.dumps(
            {
                name: result.model_dump(mode="json")
                for name, result in zip(tool_names, results, strict=True)
            }
        ),
    )
    return results[0], results[1], results[2]


async def _agent_started(
    ctx: _ExecutionContext,
    role: str,
    *,
    touch_agent: bool = True,
) -> None:
    _agent_config(ctx.workflow, role)
    key = ctx.journal.begin(f"agent_started:{role}")
    if ctx.journal.is_completed(key):
        return
    _event(
        ctx,
        RunEventType.AGENT_STARTED,
        agent_role=role,
        status=RunStatus.PROCESSING.value,
        message=f"Agent {role} started.",
    )
    if touch_agent:
        await _touch_pydantic_agent(ctx.workflow, ctx.run, role, ctx.settings)
    ctx.journal.complete(key)


async def _agent_finished(ctx: _ExecutionContext, role: str) -> None:
    key = ctx.journal.begin(f"agent_finished:{role}")
    if ctx.journal.is_completed(key):
        return
    _event(
        ctx,
        RunEventType.AGENT_FINISHED,
        agent_role=role,
        status=RunStatus.PROCESSING.value,
        message=f"Agent {role} finished.",
    )
    ctx.journal.complete(key)


async def _touch_pydantic_agent(
    workflow: WorkflowRuntime,
    run: Run,
    role: str,
    settings: Settings,
) -> None:
    if settings.environment == "test":
        return
    runtime = workflow.agents[role]
    if runtime.agent is None:
        return
    await runtime.agent.run(
        (
            f"Acknowledge the bounded {workflow.config.key} step for run {run.id}. "
            "Do not call tools; deterministic registry tools execute separately."
        ),
        deps=WorkflowAgentDeps(run=run, db=None),
        usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0),
    )


def _tool(
    ctx: _ExecutionContext,
    agent_role: str,
    tool_name: str,
    payload: BaseModel,
) -> BaseModel:
    key = ctx.journal.begin(f"tool:{agent_role}:{tool_name}")
    if ctx.journal.is_completed(key):
        output_model = ctx.registry.tool_registry.get(tool_name).output_model
        return output_model.model_validate_json(_stored_output(ctx, key))
    _event(
        ctx,
        RunEventType.TOOL_CALLED,
        agent_role=agent_role,
        tool_name=tool_name,
        tool_arguments=_summarize_payload(payload),
        status=RunStatus.PROCESSING.value,
    )
    try:
        result = ctx.registry.tool_registry.execute(tool_name, payload)
    except Exception:
        log_event(
            logger,
            "tool_execution_failed",
            level=logging.ERROR,
            run_id=ctx.run.id,
            agent_role=agent_role,
            tool_name=tool_name,
        )
        raise
    _event(
        ctx,
        RunEventType.TOOL_RESULT,
        agent_role=agent_role,
        tool_name=tool_name,
        tool_result=_summarize_payload(result),
        status=RunStatus.PROCESSING.value,
    )
    ctx.journal.complete(key, result.model_dump_json())
    return result


def _handoff(
    ctx: _ExecutionContext,
    source_role: str,
    target_role: str,
) -> None:
    source = _agent_config(ctx.workflow, source_role)
    _agent_config(ctx.workflow, target_role)
    if target_role not in source.can_handoff_to:
        raise WorkflowExecutionError(
            f"Agent '{source_role}' cannot hand off to '{target_role}'."
        )
    key = ctx.journal.begin(f"handoff:{source_role}:{target_role}")
    if ctx.journal.is_completed(key):
        return
    _event(
        ctx,
        RunEventType.HANDOFF_OCCURRED,
        handoff_source_role=source_role,
        handoff_target_role=target_role,
        status=RunStatus.PROCESSING.value,
        message=f"{source_role} handed off to {target_role}.",
    )
    ctx.journal.complete(key)


def _run_completed(ctx: _ExecutionContext) -> None:
    key = ctx.journal.begin("run_completed")
    if ctx.journal.is_completed(key):
        return
    ctx.run.completed_at = datetime.now(UTC)
    _event(
        ctx,
        RunEventType.RUN_COMPLETED,
        status=RunStatus.COMPLETED.value,
        message="Workflow completed.",
    )
    ctx.journal.complete(key)


def _run_post_processors(ctx: _ExecutionContext) -> None:
    db = ctx.db
    run = ctx.run
    workflow = ctx.workflow
    results: dict[str, dict[str, Any]] = {}
    for key in workflow.config.post_processors:
        step_key = ctx.journal.begin(f"post_processor:{key}")
        if ctx.journal.is_completed(step_key):
            results[key] = json.loads(_stored_output(ctx, step_key))
            continue
        processor = ctx.registry.post_processors[key]
        _event(
            ctx,
            RunEventType.POST_PROCESSOR_STARTED,
            post_processor_key=key,
            status=RunStatus.COMPLETED.value,
            message=f"Post-processor {key} started.",
        )
        events = _events_for_run(db, run.id)
        try:
            audit = _audit_tool_usage_and_handoffs(workflow, events)
        except Exception:
            log_event(
                logger,
                "post_processor_failed",
                level=logging.ERROR,
                run_id=run.id,
                post_processor_key=key,
            )
            raise
        results[key] = {
            "type": processor.type.value,
            "overall_assessment": audit["overall_assessment"],
            "tool_usage_findings": audit["tool_usage_findings"],
            "handoff_findings": audit["handoff_findings"],
            "suspicious_actions": audit["suspicious_actions"],
            "summary": audit["summary"],
        }
        run.post_processor_results_serialized = json.dumps(results)
        _event(
            ctx,
            RunEventType.POST_PROCESSOR_COMPLETED,
            post_processor_key=key,
            status=RunStatus.COMPLETED.value,
            tool_result={"overall_assessment": audit["overall_assessment"]},
            message=f"Post-processor {key} completed.",
        )
        ctx.journal.complete(step_key, json.dumps(results[key]))


def _completion_notification(ctx: _ExecutionContext) -> None:
    key = ctx.journal.begin("completion_notification")
    if ctx.journal.is_completed(key):
        return
    if not completion_notification_recorded(ctx.db, ctx.run):
        send_completion_notification(ctx.db, ctx.run, ctx.settings)
    ctx.journal.complete(key)


def _stored_output(ctx: _ExecutionContext, key: str) -> str:
    output = ctx.journal.output(key)
    if output is None:
        raise WorkflowExecutionError(f"Checkpoint '{key}' has no stored output.")
    return output


def _audit_tool_usage_and_handoffs(
    workflow: WorkflowRuntime,
    events: list[RunEvent],
) -> dict[str, Any]:
    configured_tools = {
        agent.role: set(agent.tools) for agent in workflow.config.agents
    }
    graph = {agent.role: set(agent.can_handoff_to) for agent in workflow.config.agents}
    suspicious: list[str] = []
    tool_findings: list[str] = []
    handoff_findings: list[str] = []

    for event in events:
        if event.event_type == RunEventType.TOOL_CALLED.value and event.tool_name:
            allowed = configured_tools.get(event.agent_role or "", set())
            if event.tool_name not in allowed:
                suspicious.append(
                    f"{event.agent_role} called unconfigured tool {event.tool_name}."
                )
            else:
                tool_findings.append(
                    f"{event.agent_role} used configured tool {event.tool_name}."
                )
        if event.event_type == RunEventType.HANDOFF_OCCURRED.value:
            source = event.handoff_source_role or ""
            target = event.handoff_target_role or ""
            if target not in graph.get(source, set()):
                suspicious.append(f"Invalid handoff observed: {source} to {target}.")
            else:
                handoff_findings.append(
                    f"Configured handoff observed: {source} to {target}."
                )

    assessment = "ok" if not suspicious else "needs_review"
    return {
        "overall_assessment": assessment,
        "tool_usage_findings": tool_findings,
        "handoff_findings": handoff_findings,
        "suspicious_actions": suspicious,
        "summary": (
            "Tool use and handoffs stayed inside the configured workflow."
            if not suspicious
            else "The audit found actions outside the configured workflow."
        ),
    }


def _agent_config(workflow: WorkflowRuntime, role: str) -> AgentWorkflowConfig:
    try:
        return workflow.agents[role].config
    except KeyError as exc:
        raise WorkflowExecutionError(f"Unknown workflow agent '{role}'.") from exc


def _parse_local_slm_project_brief(raw_output: str) -> LocalSlmProjectBrief:
    """Validate the local SLM's trained JSON brief shape."""
    text = raw_output.strip()
    if text.startswith("```"):
        raise WorkflowExecutionError("Local SLM returned markdown-fenced output.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkflowExecutionError(
            f"Local SLM returned invalid JSON: {exc.msg}."
        ) from exc
    try:
        return LocalSlmProjectBrief.model_validate(payload)
    except Exception as exc:
        raise WorkflowExecutionError(
            "Local SLM output did not match the expected brief schema."
        ) from exc


def _local_project_brief_to_run_brief(project: LocalSlmProjectBrief) -> BriefOutput:
    """Map the trained local SLM schema into the run brief shape used by the UI."""
    sections = [
        BriefSection(
            heading="Key points",
            content=_bullet_list(project.key_points) or "No key points provided.",
        ),
        BriefSection(
            heading="Risks",
            content=_bullet_list(project.risks) or "No risks identified.",
        ),
        BriefSection(
            heading="Next actions",
            content=_bullet_list(project.next_actions) or "No next actions provided.",
        ),
    ]
    return BriefOutput(
        title=project.title,
        executive_summary=project.summary,
        sections=sections,
        open_questions=project.open_questions,
        audit_notes=["Generated by local messy-brief SLM via Ollama."],
    )


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item.strip())


def _event(
    ctx: _ExecutionContext,
    event_type: RunEventType,
    *,
    status: str | None = None,
    agent_role: str | None = None,
    tool_name: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
    tool_result: dict[str, Any] | None = None,
    handoff_source_role: str | None = None,
    handoff_target_role: str | None = None,
    post_processor_key: str | None = None,
    message: str | None = None,
) -> None:
    ctx.journal.emit(
        RunEventPayload(
            event_type=event_type,
            status=status,
            agent_role=agent_role,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            tool_result=tool_result,
            handoff_source_role=handoff_source_role,
            handoff_target_role=handoff_target_role,
            post_processor_key=post_processor_key,
            message=message,
        )
    )


def _events_for_run(db: Session, run_id: int) -> list[RunEvent]:
    return (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.id.asc())
        .all()
    )


def _summarize_payload(payload: BaseModel) -> dict[str, Any]:
    data = payload.model_dump(mode="json")
    return cast(dict[str, Any], _truncate_value(data))


def _truncate_value(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 300 else f"{value[:300]}..."
    if isinstance(value, list):
        return [_truncate_value(item) for item in value[:5]]
    if isinstance(value, dict):
        return {key: _truncate_value(item) for key, item in value.items()}
    return value


def get_run_events(db: Session, run_id: int) -> list[RunEvent]:
    """Return stored events for one run in creation order."""
    return _events_for_run(db, run_id)


def build_run_execution_summary(db: Session, run: Run) -> RunExecutionSummary:
    """Return a concise run-event summary for UI and operator debugging."""
    events = _events_for_run(db, run.id)
    phase_summary: list[str] = []
    tool_counts: dict[str, int] = {}
    handoff_summary: list[str] = []
    post_processor_summary: list[str] = []

    for event in events:
        if event.event_type in {
            RunEventType.RUN_EXECUTION_STARTED.value,
            RunEventType.RUN_COMPLETED.value,
            RunEventType.RUN_FAILED.value,
            RunEventType.AGENT_STARTED.value,
            RunEventType.AGENT_FINISHED.value,
        }:
            label = event.agent_role or event.message or event.event_type
            phase_summary.append(f"{event.event_type}: {label}")
        if event.event_type == RunEventType.TOOL_RESULT.value and event.tool_name:
            tool_counts[event.tool_name] = tool_counts.get(event.tool_name, 0) + 1
        if event.event_type == RunEventType.HANDOFF_OCCURRED.value:
            handoff_summary.append(
                f"{event.handoff_source_role} to {event.handoff_target_role}"
            )
        if event.event_type == RunEventType.POST_PROCESSOR_COMPLETED.value:
            post_processor_summary.append(
                f"{event.post_processor_key}: {event.message or 'completed'}"
            )

    audit_summary = None
    if run.post_processor_results_serialized:
        results = json.loads(run.post_processor_results_serialized)
        audit = results.get("audit-tool-usage-and-handoffs")
        if isinstance(audit, dict):
            audit_summary = str(audit.get("summary") or "")

    return RunExecutionSummary(
        run_id=run.id,
        status=RunStatus(run.status),
        failure_message=run.failure_message,
        phase_summary=phase_summary,
        tool_usage_summary=[
            f"{tool_name}: {count} result event{'s' if count != 1 else ''}"
            for tool_name, count in sorted(tool_counts.items())
        ],
        handoff_summary=handoff_summary,
        audit_summary=audit_summary,
        post_processor_summary=post_processor_summary,
    )
