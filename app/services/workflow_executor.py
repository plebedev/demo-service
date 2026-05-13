"""Bounded runtime execution for the messy-notes workflow."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
import logging
from typing import Any, cast

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic_ai.usage import UsageLimits
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.models.run import Run, RunStatus
from app.models.run_event import RunEvent, RunEventType
from app.schemas.run_events import RunEventPayload
from app.schemas.runs import RunExecutionSummary
from app.services.run_events import record_run_event
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


async def execute_run_workflow(
    db: Session,
    run: Run,
    registry: WorkflowRegistry,
    settings: Settings,
) -> Run:
    """Execute one submitted messy-notes run synchronously."""
    if run.status not in {
        RunStatus.SUBMITTED.value,
        RunStatus.FAILED.value,
        RunStatus.DRAFT.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft, submitted, or failed runs can be executed.",
        )

    try:
        workflow = registry.get_workflow(run.workflow_key)
        run.status = RunStatus.PROCESSING.value
        run.failed_at = cast(Any, None)
        run.failure_message = cast(Any, None)
        run.failure_internal_reason = cast(Any, None)
        db.add(run)
        db.commit()
        db.refresh(run)
        log_event(
            logger,
            "run_execution_started",
            run_id=run.id,
            workflow_key=workflow.config.key,
        )
        _event(
            db,
            run,
            RunEventType.RUN_EXECUTION_STARTED,
            status=run.status,
            message=f"Started workflow {workflow.config.key}.",
        )

        await _execute_messy_notes(db, run, workflow, registry, settings)

        run.status = RunStatus.COMPLETED.value
        run.completed_at = datetime.now(UTC)
        run.follow_up_count = run.follow_up_count or 0
        db.add(run)
        db.commit()
        db.refresh(run)
        _event(
            db,
            run,
            RunEventType.RUN_COMPLETED,
            status=run.status,
            message="Workflow completed.",
        )
        _run_post_processors(db, run, workflow, registry)
        db.refresh(run)
        log_event(
            logger,
            "run_execution_completed",
            run_id=run.id,
            workflow_key=workflow.config.key,
        )
        return run
    except Exception as exc:
        run.status = RunStatus.FAILED.value
        run.failed_at = datetime.now(UTC)
        run.failure_message = "The run failed during bounded workflow execution."
        run.failure_internal_reason = str(exc)
        db.add(run)
        db.commit()
        db.refresh(run)
        _event(
            db,
            run,
            RunEventType.RUN_FAILED,
            status=run.status,
            message=run.failure_message,
            tool_result={"internal_reason": str(exc)[:500]},
        )
        log_event(
            logger,
            "run_execution_failed",
            level=logging.ERROR,
            run_id=run.id,
            workflow_key=run.workflow_key,
            internal_reason=str(exc),
        )
        if isinstance(exc, HTTPException):
            raise
        raise WorkflowExecutionError(str(exc)) from exc


async def _execute_messy_notes(
    db: Session,
    run: Run,
    workflow: WorkflowRuntime,
    registry: WorkflowRegistry,
    settings: Settings,
) -> None:
    if workflow.config.key == "messy-notes-local-slm":
        await _execute_messy_notes_local_slm(db, run, workflow, settings)
        return

    if workflow.config.key != "messy-notes-v1":
        raise WorkflowExecutionError(f"Unsupported workflow '{workflow.config.key}'.")

    orchestrator = workflow.config.starting_agent
    await _agent_started(db, run, workflow, orchestrator, settings)
    source_text = run.normalized_input_text or run.input_text or ""
    normalized = cast(
        Any,
        _tool(
            db,
            run,
            registry,
            orchestrator,
            "normalize_input",
            TextToolInput(text=source_text),
        ),
    )
    await _agent_finished(db, run, workflow, orchestrator, settings)

    _handoff(db, run, workflow, orchestrator, "extractor")
    await _agent_started(db, run, workflow, "extractor", settings)
    sections = cast(
        SectionsOutput,
        _tool(
            db,
            run,
            registry,
            "extractor",
            "split_into_sections",
            SectionsInput(text=normalized.text),
        ),
    )
    extraction_input = SectionsToolInput(sections=sections.sections)
    claims, decisions, action_items = _run_extraction_parallel(
        db, run, workflow, registry, extraction_input
    )
    await _agent_finished(db, run, workflow, "extractor", settings)

    _handoff(db, run, workflow, "extractor", "reconciler")
    await _agent_started(db, run, workflow, "reconciler", settings)
    reconciliation_input = ReconciliationInput(
        claims=claims.items,
        decisions=decisions.items,
        action_items=action_items.items,
    )
    duplicates = cast(
        DuplicateFindingsOutput,
        _tool(
            db,
            run,
            registry,
            "reconciler",
            "find_duplicates",
            reconciliation_input,
        ),
    )
    contradictions = cast(
        ContradictionFindingsOutput,
        _tool(
            db,
            run,
            registry,
            "reconciler",
            "find_contradictions",
            reconciliation_input,
        ),
    )
    await _agent_finished(db, run, workflow, "reconciler", settings)

    _handoff(db, run, workflow, "reconciler", "brief_writer")
    await _agent_started(db, run, workflow, "brief_writer", settings)
    brief = _tool(
        db,
        run,
        registry,
        "brief_writer",
        "format_brief",
        BriefInput(
            title=run.title,
            claims=claims.items,
            decisions=decisions.items,
            action_items=action_items.items,
            duplicates=duplicates.duplicates,
            contradictions=contradictions.contradictions,
        ),
    )
    run.output_brief_serialized = brief.model_dump_json()
    db.add(run)
    db.commit()
    db.refresh(run)
    await _agent_finished(db, run, workflow, "brief_writer", settings)


async def _execute_messy_notes_local_slm(
    db: Session,
    run: Run,
    workflow: WorkflowRuntime,
    settings: Settings,
) -> None:
    """Execute the local Ollama-backed single-model messy notes workflow."""
    role = workflow.config.starting_agent
    await _agent_started(db, run, workflow, role, settings, touch_agent=False)
    runtime = workflow.agents[role]
    if runtime.agent is None:
        raise WorkflowExecutionError(f"Workflow agent '{role}' is not executable.")

    source_text = run.normalized_input_text or run.input_text or ""
    if not source_text.strip():
        raise WorkflowExecutionError("Cannot execute local SLM workflow without input.")

    prompt = (
        "Messy notes:\n"
        f"{source_text.strip()}\n\n"
        "Return only the strict JSON project brief."
    )
    result = await runtime.agent.run(
        prompt,
        deps=WorkflowAgentDeps(run=run, db=db),
        usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0),
    )
    project_brief = _parse_local_slm_project_brief(str(result.output))
    brief = _local_project_brief_to_run_brief(project_brief)
    run.output_brief_serialized = brief.model_dump_json()
    db.add(run)
    db.commit()
    db.refresh(run)
    await _agent_finished(db, run, workflow, role, settings)


def _run_extraction_parallel(
    db: Session,
    run: Run,
    workflow: WorkflowRuntime,
    registry: WorkflowRegistry,
    payload: SectionsToolInput,
) -> tuple[ExtractedItemsOutput, ExtractedItemsOutput, ExtractedItemsOutput]:
    extractor = _agent_config(workflow, "extractor")
    tool_names = ["extract_claims", "extract_decisions", "extract_action_items"]
    if extractor.parallel is None or not extractor.parallel.enabled:
        claims = cast(
            ExtractedItemsOutput,
            _tool(db, run, registry, "extractor", "extract_claims", payload),
        )
        decisions = cast(
            ExtractedItemsOutput,
            _tool(db, run, registry, "extractor", "extract_decisions", payload),
        )
        action_items = cast(
            ExtractedItemsOutput,
            _tool(db, run, registry, "extractor", "extract_action_items", payload),
        )
        return claims, decisions, action_items

    for name in tool_names:
        _event(
            db,
            run,
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
            db,
            run,
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
    return results[0], results[1], results[2]


async def _agent_started(
    db: Session,
    run: Run,
    workflow: WorkflowRuntime,
    role: str,
    settings: Settings,
    *,
    touch_agent: bool = True,
) -> None:
    _agent_config(workflow, role)
    _event(
        db,
        run,
        RunEventType.AGENT_STARTED,
        agent_role=role,
        status=RunStatus.PROCESSING.value,
        message=f"Agent {role} started.",
    )
    if touch_agent:
        await _touch_pydantic_agent(workflow, run, role, settings)


async def _agent_finished(
    db: Session,
    run: Run,
    workflow: WorkflowRuntime,
    role: str,
    settings: Settings,
) -> None:
    del workflow, settings
    _event(
        db,
        run,
        RunEventType.AGENT_FINISHED,
        agent_role=role,
        status=RunStatus.PROCESSING.value,
        message=f"Agent {role} finished.",
    )


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
    db: Session,
    run: Run,
    registry: WorkflowRegistry,
    agent_role: str,
    tool_name: str,
    payload: BaseModel,
) -> BaseModel:
    _event(
        db,
        run,
        RunEventType.TOOL_CALLED,
        agent_role=agent_role,
        tool_name=tool_name,
        tool_arguments=_summarize_payload(payload),
        status=RunStatus.PROCESSING.value,
    )
    try:
        result = registry.tool_registry.execute(tool_name, payload)
    except Exception:
        log_event(
            logger,
            "tool_execution_failed",
            level=logging.ERROR,
            run_id=run.id,
            agent_role=agent_role,
            tool_name=tool_name,
        )
        raise
    _event(
        db,
        run,
        RunEventType.TOOL_RESULT,
        agent_role=agent_role,
        tool_name=tool_name,
        tool_result=_summarize_payload(result),
        status=RunStatus.PROCESSING.value,
    )
    return result


def _handoff(
    db: Session,
    run: Run,
    workflow: WorkflowRuntime,
    source_role: str,
    target_role: str,
) -> None:
    source = _agent_config(workflow, source_role)
    _agent_config(workflow, target_role)
    if target_role not in source.can_handoff_to:
        raise WorkflowExecutionError(
            f"Agent '{source_role}' cannot hand off to '{target_role}'."
        )
    _event(
        db,
        run,
        RunEventType.HANDOFF_OCCURRED,
        handoff_source_role=source_role,
        handoff_target_role=target_role,
        status=RunStatus.PROCESSING.value,
        message=f"{source_role} handed off to {target_role}.",
    )


def _run_post_processors(
    db: Session,
    run: Run,
    workflow: WorkflowRuntime,
    registry: WorkflowRegistry,
) -> None:
    results: dict[str, dict[str, Any]] = {}
    for key in workflow.config.post_processors:
        processor = registry.post_processors[key]
        _event(
            db,
            run,
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
        db.add(run)
        db.commit()
        db.refresh(run)
        _event(
            db,
            run,
            RunEventType.POST_PROCESSOR_COMPLETED,
            post_processor_key=key,
            status=RunStatus.COMPLETED.value,
            tool_result={"overall_assessment": audit["overall_assessment"]},
            message=f"Post-processor {key} completed.",
        )


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
    db: Session,
    run: Run,
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
    record_run_event(
        db,
        run,
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
        ),
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
