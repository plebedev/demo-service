"""Workflow tool implementations and typed contracts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from sqlalchemy.orm import Session

from app.models.run import Run
from app.services.runs import serialize_run
from app.services.tool_registry import ToolCategory, tool_decorator


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


class CaptureNotificationPreferenceInput(BaseModel):
    """Input for future notification preference capture tool."""

    wants_sms: bool
    phone_number: str | None = None


class CaptureNotificationPreferenceOutput(BaseModel):
    """Acknowledgement returned by notification preference capture."""

    wants_sms: bool
    stored: bool


class TextToolInput(BaseModel):
    """Generic text input for deterministic workflow helpers."""

    text: str = ""


class NormalizedInputOutput(BaseModel):
    """Normalized note text prepared for downstream tools."""

    text: str
    line_count: int


class NoteSection(BaseModel):
    """One extracted note section."""

    section_id: str
    heading: str
    text: str


class SectionsInput(BaseModel):
    """Input text for section splitting."""

    text: str


class SectionsOutput(BaseModel):
    """Split note sections."""

    sections: list[NoteSection]


class SectionsToolInput(BaseModel):
    """Section-based extraction input."""

    sections: list[NoteSection]


class ExtractedItem(BaseModel):
    """Small structured finding extracted from the notes."""

    text: str
    source_section_id: str
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedItemsOutput(BaseModel):
    """Collection of extracted findings."""

    items: list[ExtractedItem]


class ReconciliationInput(BaseModel):
    """Input for duplicate and contradiction checks."""

    claims: list[ExtractedItem] = Field(default_factory=list)
    decisions: list[ExtractedItem] = Field(default_factory=list)
    action_items: list[ExtractedItem] = Field(default_factory=list)


class DuplicateFinding(BaseModel):
    """Potential duplicate finding."""

    text: str
    source_section_ids: list[str]


class DuplicateFindingsOutput(BaseModel):
    """Duplicate-finding result."""

    duplicates: list[DuplicateFinding]


class ContradictionFinding(BaseModel):
    """Potential contradiction finding."""

    positive: str
    negative: str
    source_section_ids: list[str]


class ContradictionFindingsOutput(BaseModel):
    """Contradiction-finding result."""

    contradictions: list[ContradictionFinding]


class BriefInput(BaseModel):
    """Structured findings used to produce the final brief."""

    title: str | None = None
    claims: list[ExtractedItem] = Field(default_factory=list)
    decisions: list[ExtractedItem] = Field(default_factory=list)
    action_items: list[ExtractedItem] = Field(default_factory=list)
    duplicates: list[DuplicateFinding] = Field(default_factory=list)
    contradictions: list[ContradictionFinding] = Field(default_factory=list)


class BriefOutput(BaseModel):
    """Final bounded brief payload stored on the run."""

    title: str
    executive_summary: str
    sections: list[BriefSection]
    open_questions: list[str] = Field(default_factory=list)
    audit_notes: list[str] = Field(default_factory=list)


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Load normalized run inputs, file extracts, and ingestion summary.",
    prompt_instructions=(
        "Call this first when you need the persisted notes, uploaded file text, "
        "or ingestion warnings for the current run."
    ),
    input_model=RunContextInput,
    output_model=RunContextOutput,
)
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


@tool_decorator(
    ToolCategory.MUTATIVE,
    description="Persist a structured draft brief back onto the run record.",
    prompt_instructions=(
        "Only call this after you have produced a bounded structured brief that is "
        "ready to save for later review."
    ),
    input_model=PersistBriefDraftInput,
    output_model=PersistBriefDraftOutput,
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


@tool_decorator(
    ToolCategory.MUTATIVE,
    description="Store optional SMS notification preference for a run.",
    prompt_instructions=(
        "Use only to store explicit notification preference and phone number. "
        "Do not send SMS from the workflow."
    ),
    input_model=CaptureNotificationPreferenceInput,
    output_model=CaptureNotificationPreferenceOutput,
)
async def capture_notification_preference(
    ctx: RunContext[WorkflowAgentDeps],
    preference: CaptureNotificationPreferenceInput,
) -> CaptureNotificationPreferenceOutput:
    """Persist notification preference without sending a message."""
    if ctx.deps.db is None:
        raise RuntimeError("A database session is required to capture preferences.")

    from app.schemas.runs import NotificationPreferenceRequest
    from app.services.notifications import capture_notification_preference as capture

    capture(
        ctx.deps.db,
        ctx.deps.run,
        NotificationPreferenceRequest(
            wants_sms=preference.wants_sms,
            phone_number=preference.phone_number,
        ),
    )
    return CaptureNotificationPreferenceOutput(
        wants_sms=preference.wants_sms, stored=True
    )


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Normalize pasted and uploaded note text for workflow processing.",
    prompt_instructions="Use before extracting findings so later steps see stable text.",
    input_model=TextToolInput,
    output_model=NormalizedInputOutput,
)
def normalize_input(payload: TextToolInput) -> NormalizedInputOutput:
    """Normalize whitespace without changing the meaning of the notes."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in payload.text.splitlines()]
    kept = [line for line in lines if line]
    return NormalizedInputOutput(text="\n".join(kept), line_count=len(kept))


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Split normalized notes into stable sections.",
    prompt_instructions="Use after normalization before claim, decision, or action extraction.",
    input_model=SectionsInput,
    output_model=SectionsOutput,
)
def split_into_sections(payload: SectionsInput) -> SectionsOutput:
    """Split notes into stable line/paragraph sections."""
    raw_sections = re.split(r"\n{2,}|(?<=\n)", payload.text)
    sections: list[NoteSection] = []
    for index, raw_section in enumerate(raw_sections, start=1):
        text = raw_section.strip()
        if not text:
            continue
        heading = text.splitlines()[0][:80]
        sections.append(
            NoteSection(
                section_id=f"s{len(sections) + 1}",
                heading=heading,
                text=text,
            )
        )
    if not sections and payload.text.strip():
        sections.append(
            NoteSection(section_id="s1", heading="Notes", text=payload.text.strip())
        )
    return SectionsOutput(sections=sections)


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Extract factual claims from note sections.",
    prompt_instructions="Use for grounded observations, not decisions or action items.",
    input_model=SectionsToolInput,
    output_model=ExtractedItemsOutput,
)
def extract_claims(payload: SectionsToolInput) -> ExtractedItemsOutput:
    """Extract factual-looking claims from note sections."""
    items = [
        _item_from_section(section)
        for section in payload.sections
        if not _looks_like_action(section.text)
        and not _looks_like_decision(section.text)
    ]
    return ExtractedItemsOutput(items=items)


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Extract explicit decisions from note sections.",
    prompt_instructions="Use only for notes that look like decisions or approvals.",
    input_model=SectionsToolInput,
    output_model=ExtractedItemsOutput,
)
def extract_decisions(payload: SectionsToolInput) -> ExtractedItemsOutput:
    """Extract decision-looking notes."""
    items = [
        _item_from_section(section)
        for section in payload.sections
        if _looks_like_decision(section.text)
    ]
    return ExtractedItemsOutput(items=items)


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Extract action items from note sections.",
    prompt_instructions="Use for todos, asks, owners, and follow-up work.",
    input_model=SectionsToolInput,
    output_model=ExtractedItemsOutput,
)
def extract_action_items(payload: SectionsToolInput) -> ExtractedItemsOutput:
    """Extract action-item-looking notes."""
    items = [
        _item_from_section(section)
        for section in payload.sections
        if _looks_like_action(section.text)
    ]
    return ExtractedItemsOutput(items=items)


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Find duplicate extracted findings.",
    prompt_instructions="Use after extraction and before writing the brief.",
    input_model=ReconciliationInput,
    output_model=DuplicateFindingsOutput,
)
def find_duplicates(payload: ReconciliationInput) -> DuplicateFindingsOutput:
    """Find repeated or near-repeated findings by normalized text."""
    buckets: dict[str, list[ExtractedItem]] = {}
    for item in [*payload.claims, *payload.decisions, *payload.action_items]:
        key = re.sub(r"[^a-z0-9]+", " ", item.text.lower()).strip()
        buckets.setdefault(key, []).append(item)
    duplicates = [
        DuplicateFinding(
            text=items[0].text,
            source_section_ids=sorted({item.source_section_id for item in items}),
        )
        for items in buckets.values()
        if len(items) > 1
    ]
    return DuplicateFindingsOutput(duplicates=duplicates)


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Find simple contradictions or tensions in extracted findings.",
    prompt_instructions="Use after extraction and before writing the brief.",
    input_model=ReconciliationInput,
    output_model=ContradictionFindingsOutput,
)
def find_contradictions(payload: ReconciliationInput) -> ContradictionFindingsOutput:
    """Find simple positive/negative tension in extracted findings."""
    items = [*payload.claims, *payload.decisions, *payload.action_items]
    negatives = [item for item in items if _contains_negative_signal(item.text)]
    positives = [item for item in items if _contains_positive_signal(item.text)]
    contradictions: list[ContradictionFinding] = []
    for negative in negatives:
        negative_terms = _meaningful_terms(negative.text)
        for positive in positives:
            if negative.source_section_id == positive.source_section_id:
                continue
            if negative_terms & _meaningful_terms(positive.text):
                contradictions.append(
                    ContradictionFinding(
                        positive=positive.text,
                        negative=negative.text,
                        source_section_ids=[
                            positive.source_section_id,
                            negative.source_section_id,
                        ],
                    )
                )
                break
    return ContradictionFindingsOutput(contradictions=contradictions)


@tool_decorator(
    ToolCategory.READ_ONLY,
    description="Format reconciled findings into a concise structured brief.",
    prompt_instructions="Use as the final tool before persisting the completed run result.",
    input_model=BriefInput,
    output_model=BriefOutput,
)
def format_brief(payload: BriefInput) -> BriefOutput:
    """Format extracted findings into a concise structured brief."""
    title = payload.title or "Messy notes brief"
    summary_parts = []
    if payload.claims:
        summary_parts.append(f"{len(payload.claims)} grounded observations")
    if payload.decisions:
        summary_parts.append(f"{len(payload.decisions)} decisions")
    if payload.action_items:
        summary_parts.append(f"{len(payload.action_items)} action items")
    executive_summary = (
        "This brief summarizes "
        + ", ".join(summary_parts)
        + " from the submitted notes."
        if summary_parts
        else "The submitted notes did not contain enough structured detail for a rich brief."
    )
    sections = [
        BriefSection(
            heading="Key observations",
            content=_join_items(payload.claims)
            or "No clear factual claims were found.",
        ),
        BriefSection(
            heading="Decisions",
            content=_join_items(payload.decisions)
            or "No explicit decisions were found.",
        ),
        BriefSection(
            heading="Action items",
            content=_join_items(payload.action_items)
            or "No explicit action items were found.",
        ),
    ]
    open_questions = [
        "Resolve duplicate or overlapping notes before treating them as separate facts."
        for _ in payload.duplicates[:1]
    ]
    open_questions.extend(
        "Confirm contradictory notes before acting on the brief."
        for _ in payload.contradictions[:1]
    )
    return BriefOutput(
        title=title,
        executive_summary=executive_summary,
        sections=sections,
        open_questions=open_questions,
        audit_notes=[
            f"Duplicate findings: {len(payload.duplicates)}",
            f"Potential contradictions: {len(payload.contradictions)}",
        ],
    )


def _item_from_section(section: NoteSection) -> ExtractedItem:
    return ExtractedItem(
        text=section.text,
        source_section_id=section.section_id,
        confidence=0.72,
    )


def _looks_like_decision(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in ("decided", "decision", "approved", "will ", "we will")
    )


def _looks_like_action(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "todo",
            "action",
            "need ",
            "needs ",
            "ask ",
            "owner",
            "follow up",
        )
    )


def _contains_negative_signal(text: str) -> bool:
    return bool(
        re.search(r"\b(no|not|blocked|cancel|delay|risk|cannot|won't)\b", text.lower())
    )


def _contains_positive_signal(text: str) -> bool:
    return bool(
        re.search(r"\b(yes|approved|will|go|ready|can|confirmed)\b", text.lower())
    )


def _meaningful_terms(text: str) -> set[str]:
    stopwords = {"the", "and", "for", "with", "that", "this", "will", "not", "need"}
    return {
        term
        for term in re.findall(r"[a-z0-9]{4,}", text.lower())
        if term not in stopwords
    }


def _join_items(items: list[ExtractedItem]) -> str:
    return "\n".join(f"- {item.text}" for item in items[:8])
