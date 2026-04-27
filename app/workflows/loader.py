"""Startup loader for workflow and post-processor YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from fastapi import FastAPI
from pydantic_ai import Agent
import yaml  # type: ignore[import-untyped]

from app.core.config import Settings
from app.services.model_factory import (
    build_model_settings,
    create_model,
    provider_is_implemented,
    required_api_key_env_var,
)
from app.services.tool_registry import WorkflowToolRegistry, build_tool_registry
from app.workflows.config_models import (
    AgentWorkflowConfig,
    PostProcessorCatalog,
    PostProcessorConfig,
    WorkflowConfig,
)
from app.workflows.tools import WorkflowAgentDeps

ConfigModelT = TypeVar("ConfigModelT", WorkflowConfig, PostProcessorCatalog)


@dataclass(frozen=True)
class WorkflowAgentRuntime:
    """Resolved runtime metadata for one configured agent."""

    config: AgentWorkflowConfig
    system_prompt: str
    agent: Agent[WorkflowAgentDeps, str] | None


@dataclass(frozen=True)
class WorkflowRuntime:
    """Resolved runtime metadata for one workflow definition."""

    config: WorkflowConfig
    agents: dict[str, WorkflowAgentRuntime]


@dataclass(frozen=True)
class WorkflowRegistry:
    """Loaded workflow and post-processor configuration registry."""

    workflows: dict[str, WorkflowRuntime]
    post_processors: dict[str, PostProcessorConfig]
    tool_registry: WorkflowToolRegistry

    def get_workflow(self, key: str) -> WorkflowRuntime:
        """Return one loaded workflow by key."""
        try:
            return self.workflows[key]
        except KeyError as exc:
            raise KeyError(f"Unknown workflow '{key}'.") from exc


def assemble_system_prompt(
    base_prompt: str, tool_registry: WorkflowToolRegistry, tool_names: list[str]
) -> str:
    """Build the final system prompt from base agent prompt and tool metadata."""
    tool_block = tool_registry.prompt_block(tool_names)
    if tool_block is None:
        return base_prompt.strip()
    return f"{base_prompt.strip()}\n\n{tool_block}"


def load_workflow_registry(settings: Settings) -> WorkflowRegistry:
    """Load, validate, and resolve workflow runtime metadata."""
    tool_registry = build_tool_registry()
    post_processors = _load_post_processors(settings.post_processor_config_path)
    workflows: dict[str, WorkflowRuntime] = {}

    for workflow_path in sorted(Path(settings.workflow_config_dir).glob("*.yaml")):
        workflow = _load_yaml_model(workflow_path, WorkflowConfig)
        _validate_workflow_references(workflow, post_processors, tool_registry)
        if workflow.key in workflows:
            raise ValueError(
                f"Duplicate workflow key '{workflow.key}' loaded at startup."
            )
        workflows[workflow.key] = WorkflowRuntime(
            config=workflow,
            agents={
                agent.role: WorkflowAgentRuntime(
                    config=agent,
                    system_prompt=assemble_system_prompt(
                        agent.system_prompt, tool_registry, agent.tools
                    ),
                    agent=_build_agent_runtime(agent, tool_registry, settings),
                )
                for agent in workflow.agents
            },
        )

    if not workflows:
        raise ValueError(
            f"No workflow YAML files found in '{settings.workflow_config_dir}'."
        )
    if settings.default_workflow_key not in workflows:
        raise ValueError(
            f"DEFAULT_WORKFLOW_KEY '{settings.default_workflow_key}' is not defined in workflow YAML."
        )

    return WorkflowRegistry(
        workflows=workflows,
        post_processors=post_processors,
        tool_registry=tool_registry,
    )


def attach_workflow_registry(app: FastAPI, settings: Settings) -> WorkflowRegistry:
    """Load the workflow registry and attach it to FastAPI state."""
    registry = load_workflow_registry(settings)
    app.state.workflow_registry = registry
    return registry


def _load_post_processors(path_text: str) -> dict[str, PostProcessorConfig]:
    path = Path(path_text)
    catalog = _load_yaml_model(path, PostProcessorCatalog)
    return {processor.key: processor for processor in catalog.post_processors}


def _load_yaml_model(path: Path, model_type: type[ConfigModelT]) -> ConfigModelT:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing workflow configuration file: {path}") from exc
    if payload is None:
        raise ValueError(f"Configuration file '{path}' is empty.")
    try:
        return model_type.model_validate(payload)
    except Exception as exc:  # pragma: no cover - pydantic error text is enough
        raise ValueError(f"Invalid configuration in '{path}': {exc}") from exc


def _validate_workflow_references(
    workflow: WorkflowConfig,
    post_processors: dict[str, PostProcessorConfig],
    tool_registry: WorkflowToolRegistry,
) -> None:
    missing_post_processors = [
        key for key in workflow.post_processors if key not in post_processors
    ]
    if missing_post_processors:
        missing = ", ".join(missing_post_processors)
        raise ValueError(
            f"Workflow '{workflow.key}' references unknown post-processors: {missing}"
        )

    for agent in workflow.agents:
        tool_registry.validate_tool_names(workflow.key, agent.tools)


def _build_agent_runtime(
    agent: AgentWorkflowConfig,
    tool_registry: WorkflowToolRegistry,
    settings: Settings,
) -> Agent[WorkflowAgentDeps, str] | None:
    if not provider_is_implemented(agent.provider):
        return None

    try:
        model = create_model(agent.provider, agent.model, settings)
    except (ValueError, ImportError):
        return None
    return Agent(
        model=model,
        instructions=assemble_system_prompt(
            agent.system_prompt, tool_registry, agent.tools
        ),
        tools=[tool.to_pydantic_tool() for tool in tool_registry.resolve(agent.tools)],
        deps_type=WorkflowAgentDeps,
        output_type=str,
        model_settings=build_model_settings(agent),
    )
