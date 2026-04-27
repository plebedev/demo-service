"""Workflow tool implementations and typed contracts."""

from __future__ import annotations

from dataclasses import dataclass
import json

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from sqlalchemy.orm import Session

from app.models.run import Run
from app.services.runs import serialize_run


@dataclass
class WorkflowAgentDeps:
    """Dependencies shared with PydanticAI agents for this demo."""

    run: Run
    db: Session | None = None


class RunContextInput(BaseModel):
    """Empty input contract for loading normalized run context."""


class RunContextOutput(BaseModel):
    """Structured run context available to workflow agents."""

    run_id: int
    workflow_key: str
    title: str | None
    normalized_input_text: str | None
    ingestion_summary: dict[str, object] | None
    uploaded_files: list[dict[str, object]]


class BriefSection(BaseModel):
    """One structured section in a persisted draft brief."""

    heading: str = Field(min_length=1)
    content: str = Field(min_length=1)


class PersistBriefDraftInput(BaseModel):
    """Structured brief payload for the future brief writer."""

    title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    sections: list[BriefSection] = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)


class PersistBriefDraftOutput(BaseModel):
    """Acknowledgement returned after brief draft persistence."""

    run_id: int
    persisted: bool


async def load_run_context(ctx: RunContext[WorkflowAgentDeps]) -> RunContextOutput:
    """Return the normalized run data already persisted by ingestion."""
    run_payload = serialize_run(ctx.deps.run)
    return RunContextOutput(
        run_id=run_payload.id,
        workflow_key=run_payload.workflow_key,
        title=run_payload.title,
        normalized_input_text=run_payload.normalized_input_text,
        ingestion_summary=(
            run_payload.ingestion_summary_json.model_dump(mode="json")
            if run_payload.ingestion_summary_json is not None
            else None
        ),
        uploaded_files=[
            file.model_dump(mode="json")
            for file in (run_payload.uploaded_files_json or [])
        ],
    )


async def persist_brief_draft(
    ctx: RunContext[WorkflowAgentDeps], brief: PersistBriefDraftInput
) -> PersistBriefDraftOutput:
    """Persist a draft brief shape back to the run for later milestones."""
    if ctx.deps.db is None:
        raise RuntimeError("A database session is required to persist a brief draft.")

    ctx.deps.run.output_brief_serialized = json.dumps(brief.model_dump(mode="json"))
    ctx.deps.db.add(ctx.deps.run)
    ctx.deps.db.commit()
    ctx.deps.db.refresh(ctx.deps.run)
    return PersistBriefDraftOutput(run_id=ctx.deps.run.id, persisted=True)
