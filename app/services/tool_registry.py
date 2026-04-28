"""Typed workflow tool registry and prompt assembly metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from pydantic import BaseModel
from pydantic_ai import Tool

from app.workflows.tools import (
    BriefInput,
    BriefOutput,
    ContradictionFindingsOutput,
    DuplicateFindingsOutput,
    ExtractedItemsOutput,
    NormalizedInputOutput,
    PersistBriefDraftInput,
    PersistBriefDraftOutput,
    ReconciliationInput,
    RunContextInput,
    RunContextOutput,
    SectionsInput,
    SectionsOutput,
    SectionsToolInput,
    TextToolInput,
    WorkflowAgentDeps,
    extract_action_items,
    extract_claims,
    extract_decisions,
    find_contradictions,
    find_duplicates,
    format_brief,
    load_run_context,
    normalize_input,
    persist_brief_draft,
    split_into_sections,
)


class ToolCategory(StrEnum):
    """Supported classes of workflow tools."""

    READ_ONLY = "read_only"
    MUTATIVE = "mutative"


@dataclass(frozen=True)
class ToolRegistryEntry:
    """Metadata for a tool exposed to workflow agents."""

    name: str
    description: str
    prompt_instructions: str
    implementation: Callable[..., Any]
    category: ToolCategory
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    provider_override: str | None = None
    model_override: str | None = None
    implemented: bool = True

    def to_pydantic_tool(self) -> Tool[WorkflowAgentDeps]:
        """Convert registry metadata into a PydanticAI tool wrapper."""
        return Tool(
            self.implementation,
            name=self.name,
            description=self.description,
        )

    def execute(self, payload: BaseModel) -> BaseModel:
        """Execute a deterministic registry tool with typed input/output."""
        result = self.implementation(payload)
        if isinstance(result, self.output_model):
            return result
        return self.output_model.model_validate(result)


class WorkflowToolRegistry:
    """In-memory registry for the demo workflow tools."""

    def __init__(self, entries: list[ToolRegistryEntry]) -> None:
        self._entries = {entry.name: entry for entry in entries}

    def get(self, name: str) -> ToolRegistryEntry:
        """Return one registry entry or raise a clear lookup error."""
        try:
            return self._entries[name]
        except KeyError as exc:
            raise KeyError(f"Unknown workflow tool '{name}'.") from exc

    def resolve(self, names: list[str]) -> list[ToolRegistryEntry]:
        """Resolve a configured tool list into concrete registry entries."""
        return [self.get(name) for name in names]

    def validate_tool_names(self, workflow_key: str, tool_names: list[str]) -> None:
        """Fail fast when YAML references unknown tool names."""
        for tool_name in tool_names:
            self.get(tool_name)

    def prompt_block(self, tool_names: list[str]) -> str | None:
        """Build the tool-instruction prompt block for one agent."""
        tools = self.resolve(tool_names)
        if not tools:
            return None
        lines = ["Tool instructions:"]
        for tool in tools:
            lines.append(f"- {tool.name}: {tool.prompt_instructions}")
        return "\n".join(lines)

    def execute(self, name: str, payload: BaseModel) -> BaseModel:
        """Execute one registered deterministic tool."""
        return self.get(name).execute(payload)


def build_tool_registry() -> WorkflowToolRegistry:
    """Build the workflow tool registry used at startup."""
    return WorkflowToolRegistry(
        entries=[
            ToolRegistryEntry(
                name="load_run_context",
                description="Load normalized run inputs, file extracts, and ingestion summary.",
                prompt_instructions=(
                    "Call this first when you need the persisted notes, uploaded file text, "
                    "or ingestion warnings for the current run."
                ),
                implementation=load_run_context,
                category=ToolCategory.READ_ONLY,
                input_model=RunContextInput,
                output_model=RunContextOutput,
            ),
            ToolRegistryEntry(
                name="persist_brief_draft",
                description="Persist a structured draft brief back onto the run record.",
                prompt_instructions=(
                    "Only call this after you have produced a bounded structured brief that is "
                    "ready to save for later review."
                ),
                implementation=persist_brief_draft,
                category=ToolCategory.MUTATIVE,
                input_model=PersistBriefDraftInput,
                output_model=PersistBriefDraftOutput,
            ),
            ToolRegistryEntry(
                name="normalize_input",
                description="Normalize pasted and uploaded note text for workflow processing.",
                prompt_instructions="Use before extracting findings so later steps see stable text.",
                implementation=normalize_input,
                category=ToolCategory.READ_ONLY,
                input_model=TextToolInput,
                output_model=NormalizedInputOutput,
            ),
            ToolRegistryEntry(
                name="split_into_sections",
                description="Split normalized notes into stable sections.",
                prompt_instructions="Use after normalization before claim, decision, or action extraction.",
                implementation=split_into_sections,
                category=ToolCategory.READ_ONLY,
                input_model=SectionsInput,
                output_model=SectionsOutput,
            ),
            ToolRegistryEntry(
                name="extract_claims",
                description="Extract factual claims from note sections.",
                prompt_instructions="Use for grounded observations, not decisions or action items.",
                implementation=extract_claims,
                category=ToolCategory.READ_ONLY,
                input_model=SectionsToolInput,
                output_model=ExtractedItemsOutput,
            ),
            ToolRegistryEntry(
                name="extract_decisions",
                description="Extract explicit decisions from note sections.",
                prompt_instructions="Use only for notes that look like decisions or approvals.",
                implementation=extract_decisions,
                category=ToolCategory.READ_ONLY,
                input_model=SectionsToolInput,
                output_model=ExtractedItemsOutput,
            ),
            ToolRegistryEntry(
                name="extract_action_items",
                description="Extract action items from note sections.",
                prompt_instructions="Use for todos, asks, owners, and follow-up work.",
                implementation=extract_action_items,
                category=ToolCategory.READ_ONLY,
                input_model=SectionsToolInput,
                output_model=ExtractedItemsOutput,
            ),
            ToolRegistryEntry(
                name="find_duplicates",
                description="Find duplicate extracted findings.",
                prompt_instructions="Use after extraction and before writing the brief.",
                implementation=find_duplicates,
                category=ToolCategory.READ_ONLY,
                input_model=ReconciliationInput,
                output_model=DuplicateFindingsOutput,
            ),
            ToolRegistryEntry(
                name="find_contradictions",
                description="Find simple contradictions or tensions in extracted findings.",
                prompt_instructions="Use after extraction and before writing the brief.",
                implementation=find_contradictions,
                category=ToolCategory.READ_ONLY,
                input_model=ReconciliationInput,
                output_model=ContradictionFindingsOutput,
            ),
            ToolRegistryEntry(
                name="format_brief",
                description="Format reconciled findings into a concise structured brief.",
                prompt_instructions="Use as the final tool before persisting the completed run result.",
                implementation=format_brief,
                category=ToolCategory.READ_ONLY,
                input_model=BriefInput,
                output_model=BriefOutput,
            ),
        ]
    )
