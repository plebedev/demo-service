"""Typed YAML configuration models for demo workflows."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkflowProvider(StrEnum):
    """Supported LLM providers for workflow agents and post-processors."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    FIREWORKS = "fireworks"
    OPENROUTER = "openrouter"


class ParallelExecutionConfig(BaseModel):
    """Future-facing metadata for bounded parallel agent execution."""

    enabled: bool = True
    group: str | None = None
    can_run_with: list[str] = Field(default_factory=list)


class WorkflowFlags(BaseModel):
    """Workflow-level switches reserved for near-future milestones."""

    allow_single_follow_up: bool = True
    require_structured_brief_output: bool = True
    audit_run_events: bool = True


class AgentWorkflowConfig(BaseModel):
    """Per-agent workflow configuration loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    provider: WorkflowProvider
    model: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    timeout: float | None = Field(default=None, gt=0.0)
    tools: list[str] = Field(default_factory=list)
    can_handoff_to: list[str] = Field(default_factory=list)
    parallel: ParallelExecutionConfig | None = None

    @model_validator(mode="after")
    def validate_unique_tool_names(self) -> "AgentWorkflowConfig":
        """Keep per-agent tool access explicit and duplicate-free."""
        if len(self.tools) != len(set(self.tools)):
            raise ValueError(f"Agent '{self.role}' lists duplicate tool names.")
        if len(self.can_handoff_to) != len(set(self.can_handoff_to)):
            raise ValueError(f"Agent '{self.role}' lists duplicate handoff targets.")
        return self


class WorkflowConfig(BaseModel):
    """One config-driven demo workflow."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    starting_agent: str = Field(min_length=1)
    post_processors: list[str] = Field(default_factory=list)
    flags: WorkflowFlags = Field(default_factory=WorkflowFlags)
    agents: list[AgentWorkflowConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_agent_relationships(self) -> "WorkflowConfig":
        """Validate duplicate roles, start agent, handoffs, and parallel metadata."""
        roles = [agent.role for agent in self.agents]
        if len(roles) != len(set(roles)):
            raise ValueError(
                f"Workflow '{self.key}' defines duplicate agent roles: {roles}"
            )
        if self.starting_agent not in roles:
            raise ValueError(
                f"Workflow '{self.key}' starting agent '{self.starting_agent}' does not exist."
            )

        valid_roles = set(roles)
        for agent in self.agents:
            unknown_targets = sorted(set(agent.can_handoff_to) - valid_roles)
            if unknown_targets:
                raise ValueError(
                    f"Workflow '{self.key}' agent '{agent.role}' references unknown handoff targets: {', '.join(unknown_targets)}"
                )
            if agent.parallel is not None:
                unknown_parallel_roles = sorted(
                    set(agent.parallel.can_run_with) - valid_roles
                )
                if agent.role in agent.parallel.can_run_with:
                    raise ValueError(
                        f"Workflow '{self.key}' agent '{agent.role}' cannot list itself in parallel.can_run_with."
                    )
                if unknown_parallel_roles:
                    raise ValueError(
                        f"Workflow '{self.key}' agent '{agent.role}' references unknown parallel peers: {', '.join(unknown_parallel_roles)}"
                    )
        return self


class PostProcessorType(StrEnum):
    """Supported workflow-level post-processing hooks."""

    AUDIT_TOOL_USAGE_AND_HANDOFFS = "audit_tool_usage_and_handoffs"


class PostProcessorConfig(BaseModel):
    """Typed config for one post-processor entry."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    type: PostProcessorType
    description: str = Field(min_length=1)
    provider: WorkflowProvider
    model: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    prompt_template: str = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    timeout: float | None = Field(default=None, gt=0.0)


class PostProcessorCatalog(BaseModel):
    """Top-level YAML container for post-processor definitions."""

    model_config = ConfigDict(extra="forbid")

    post_processors: list[PostProcessorConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_keys(self) -> "PostProcessorCatalog":
        """Ensure post-processor keys stay unique and addressable."""
        keys = [processor.key for processor in self.post_processors]
        if len(keys) != len(set(keys)):
            raise ValueError(f"Duplicate post-processor keys defined: {keys}")
        return self
