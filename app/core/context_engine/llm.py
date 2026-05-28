"""Generic LLM execution contracts for Context Engine flows."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
import logging
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.usage import UsageLimits
import yaml  # type: ignore[import-untyped]

from app.core.config import Settings
from app.services.model_factory import (
    create_model,
    create_provider_model_settings,
    provider_is_implemented,
)
from app.workflows.config_models import WorkflowProvider

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)
logger = logging.getLogger(__name__)
_LOG_TEXT_LIMIT = 12_000
_LOG_MESSAGES_LIMIT = 40_000


class ContextExecutionMode(StrEnum):
    """Supported Context Engine execution modes."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HYBRID = "hybrid"


class ModelProfileConfig(BaseModel):
    """Configurable model profile reused by Context Engine steps."""

    model_config = ConfigDict(extra="forbid")

    provider: WorkflowProvider
    model: str = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    timeout: float | None = Field(default=None, gt=0.0)
    structured_output: bool = True


class ContextModelStepConfig(BaseModel):
    """One configured model-backed step within a Context Engine flow."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    model_profile: str | None = None
    prompt_template: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)


class ContextExecutionFlowConfig(BaseModel):
    """Flow-level execution configuration for one domain."""

    model_config = ConfigDict(extra="forbid")

    domain_id: str = Field(min_length=1)
    flow_id: str = Field(min_length=1)
    mode: ContextExecutionMode | None = None
    model_profile: str | None = None
    steps: list[ContextModelStepConfig] = Field(default_factory=list)


class ContextModelFlowCatalog(BaseModel):
    """Top-level YAML catalog for Context Engine model flows."""

    model_config = ConfigDict(extra="forbid")

    default_mode: ContextExecutionMode = ContextExecutionMode.HYBRID
    default_model_profile: str | None = None
    model_profiles: dict[str, ModelProfileConfig] = Field(default_factory=dict)
    flows: list[ContextExecutionFlowConfig] = Field(default_factory=list)

    def resolve_step(
        self,
        *,
        domain_id: str,
        flow_id: str,
        step_id: str,
        purpose: str | None = None,
        mode_override: ContextExecutionMode | None = None,
    ) -> "ResolvedContextModelStep":
        """Resolve domain/flow/step model configuration or raise clearly."""
        flow = next(
            (
                candidate
                for candidate in self.flows
                if candidate.domain_id == domain_id and candidate.flow_id == flow_id
            ),
            None,
        )
        if flow is None:
            raise ValueError(
                f"No Context Engine model flow configured for {domain_id}/{flow_id}."
            )
        step = next(
            (candidate for candidate in flow.steps if candidate.id == step_id), None
        )
        if step is None:
            raise ValueError(
                f"No Context Engine model step configured for "
                f"{domain_id}/{flow_id}/{step_id}."
            )
        if purpose is not None and step.purpose != purpose:
            raise ValueError(
                f"Context Engine step {domain_id}/{flow_id}/{step_id} has purpose "
                f"'{step.purpose}', expected '{purpose}'."
            )
        profile_id = (
            step.model_profile or flow.model_profile or self.default_model_profile
        )
        if profile_id is None:
            raise ValueError(
                f"Context Engine step {domain_id}/{flow_id}/{step_id} has no model profile."
            )
        try:
            profile = self.model_profiles[profile_id]
        except KeyError as exc:
            raise ValueError(
                f"Context Engine model profile '{profile_id}' is not configured."
            ) from exc
        return ResolvedContextModelStep(
            domain_id=domain_id,
            flow_id=flow_id,
            step_id=step_id,
            purpose=step.purpose,
            mode=mode_override or flow.mode or self.default_mode,
            model_profile_id=profile_id,
            model_profile=profile,
            prompt_template=step.prompt_template,
            prompt_version=step.prompt_version,
        )


@dataclass(frozen=True)
class ResolvedContextModelStep:
    """Resolved runtime config for one Context Engine model step."""

    domain_id: str
    flow_id: str
    step_id: str
    purpose: str
    mode: ContextExecutionMode
    model_profile_id: str
    model_profile: ModelProfileConfig
    prompt_template: str
    prompt_version: str


class ContextModelRunner(Protocol):
    """Provider-agnostic structured model runner."""

    def run_structured(
        self,
        *,
        step: ResolvedContextModelStep,
        instructions: str,
        prompt: str,
        output_type: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Run a single structured-output model request."""
        ...


class PydanticAIContextModelRunner:
    """Structured Context Engine model runner using existing PydanticAI factory."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run_structured(
        self,
        *,
        step: ResolvedContextModelStep,
        instructions: str,
        prompt: str,
        output_type: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Run one bounded PydanticAI request with the configured profile."""
        profile = step.model_profile
        if not profile.structured_output:
            raise ValueError(
                f"Context Engine step {step.domain_id}/{step.flow_id}/{step.step_id} "
                "requires structured_output=true."
            )
        if not provider_is_implemented(profile.provider):
            raise ValueError(
                f"Provider '{profile.provider.value}' is not implemented for Context Engine."
            )
        model = create_model(profile.provider, profile.model, self.settings)
        agent = Agent(
            model=model,
            instructions=instructions,
            output_type=output_type,
            model_settings=create_provider_model_settings(
                provider=profile.provider,
                timeout=profile.timeout,
                temperature=profile.temperature,
                max_tokens=profile.max_tokens,
            ),
        )

        async def _run() -> StructuredOutputT:
            logger.info(
                "context_engine_llm_request_start domain=%s flow=%s step=%s "
                "purpose=%s provider=%s model_profile=%s prompt_chars=%d "
                "instructions_chars=%d output_type=%s output_schema_chars=%d "
                "max_tokens=%s timeout=%s",
                step.domain_id,
                step.flow_id,
                step.step_id,
                step.purpose,
                profile.provider.value,
                step.model_profile_id,
                len(prompt),
                len(instructions),
                output_type.__name__,
                len(json.dumps(output_type.model_json_schema(), default=str)),
                profile.max_tokens,
                profile.timeout,
            )
            with capture_run_messages() as messages:
                try:
                    result = await agent.run(
                        prompt,
                        usage_limits=UsageLimits(request_limit=3, tool_calls_limit=0),
                    )
                except Exception as exc:
                    logger.exception(
                        "context_engine_llm_request_failed domain=%s flow=%s "
                        "step=%s purpose=%s provider=%s model_profile=%s "
                        "output_type=%s exception_type=%s exception_repr=%r "
                        "captured_messages=%s",
                        step.domain_id,
                        step.flow_id,
                        step.step_id,
                        step.purpose,
                        profile.provider.value,
                        step.model_profile_id,
                        output_type.__name__,
                        type(exc).__name__,
                        exc,
                        _format_captured_messages(messages),
                    )
                    raise
            logger.info(
                "context_engine_llm_request_succeeded domain=%s flow=%s step=%s "
                "purpose=%s provider=%s model_profile=%s output_type=%s "
                "captured_messages=%s",
                step.domain_id,
                step.flow_id,
                step.step_id,
                step.purpose,
                profile.provider.value,
                step.model_profile_id,
                output_type.__name__,
                _format_captured_message_metadata(messages),
            )
            return result.output

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_run())
        raise RuntimeError(
            "Context Engine synchronous LLM execution cannot run inside an event loop."
        )


@dataclass(frozen=True)
class ContextExecutionContext:
    """Runtime helper passed to domain extensions."""

    catalog: ContextModelFlowCatalog
    runner: ContextModelRunner
    prompt_root: Path
    mode_override: ContextExecutionMode | None = None

    def resolve_step(
        self,
        *,
        domain_id: str,
        flow_id: str,
        step_id: str,
        purpose: str | None = None,
    ) -> ResolvedContextModelStep:
        """Resolve a configured Context Engine step."""
        return self.catalog.resolve_step(
            domain_id=domain_id,
            flow_id=flow_id,
            step_id=step_id,
            purpose=purpose,
            mode_override=self.mode_override,
        )

    def load_prompt(self, step: ResolvedContextModelStep) -> str:
        """Load a prompt template from the configured prompt root."""
        prompt_path = (self.prompt_root / step.prompt_template).resolve()
        root = self.prompt_root.resolve()
        if root not in prompt_path.parents and prompt_path != root:
            raise ValueError("Context Engine prompt template path escapes prompt root.")
        return prompt_path.read_text(encoding="utf-8")

    def run_structured(
        self,
        *,
        step: ResolvedContextModelStep,
        instructions: str,
        prompt: str,
        output_type: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Run one structured model step."""
        return self.runner.run_structured(
            step=step,
            instructions=instructions,
            prompt=prompt,
            output_type=output_type,
        )


def load_context_model_flow_catalog(path_text: str) -> ContextModelFlowCatalog:
    """Load Context Engine model flow configuration from YAML."""
    path = Path(path_text)
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing Context Engine model configuration: {path}") from exc
    if payload is None:
        raise ValueError(f"Context Engine model configuration '{path}' is empty.")
    try:
        return ContextModelFlowCatalog.model_validate(payload)
    except Exception as exc:
        raise ValueError(
            f"Invalid Context Engine model configuration in '{path}': {exc}"
        ) from exc


def metadata_for_generated_step(step: ResolvedContextModelStep) -> dict[str, Any]:
    """Return durable metadata for model-generated Context Engine records."""
    return {
        "generated_by": "llm",
        "model_profile": step.model_profile_id,
        "prompt_template": step.prompt_template,
        "prompt_version": step.prompt_version,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _format_captured_message_metadata(messages: list[Any]) -> str:
    """Return compact metadata for successful PydanticAI message exchanges."""
    return _truncate_text(
        json.dumps([_message_metadata(message) for message in messages], default=str),
        _LOG_TEXT_LIMIT,
    )


def _format_captured_messages(messages: list[Any]) -> str:
    """Return failure diagnostics for PydanticAI message exchanges."""
    return _truncate_text(
        json.dumps([_message_payload(message) for message in messages], default=str),
        _LOG_MESSAGES_LIMIT,
    )


def _message_metadata(message: Any) -> dict[str, Any]:
    """Return concise metadata for one PydanticAI message."""
    return {
        "kind": getattr(message, "kind", None),
        "model_name": getattr(message, "model_name", None),
        "provider_name": getattr(message, "provider_name", None),
        "finish_reason": getattr(message, "finish_reason", None),
        "usage": _safe_payload(getattr(message, "usage", None)),
        "parts": [
            {
                "part_kind": getattr(part, "part_kind", None),
                "tool_name": getattr(part, "tool_name", None),
                "content_chars": len(str(getattr(part, "content", ""))),
                "args_chars": len(str(getattr(part, "args", ""))),
            }
            for part in getattr(message, "parts", [])
        ],
    }


def _message_payload(message: Any) -> dict[str, Any]:
    """Return debuggable content for one PydanticAI message."""
    payload = _message_metadata(message)
    payload["parts"] = [_part_payload(part) for part in getattr(message, "parts", [])]
    return payload


def _part_payload(part: Any) -> dict[str, Any]:
    """Return debuggable content for one PydanticAI message part."""
    payload: dict[str, Any] = {
        "part_kind": getattr(part, "part_kind", None),
        "tool_name": getattr(part, "tool_name", None),
        "provider_name": getattr(part, "provider_name", None),
        "provider_details": _safe_payload(getattr(part, "provider_details", None)),
    }
    if hasattr(part, "content"):
        payload["content"] = _truncate_text(
            str(getattr(part, "content")), _LOG_TEXT_LIMIT
        )
    if hasattr(part, "args"):
        payload["args"] = _truncate_text(str(getattr(part, "args")), _LOG_TEXT_LIMIT)
    return payload


def _safe_payload(value: Any) -> Any:
    """Return a JSON-serializable debug payload."""
    if value is None:
        return None
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict | list | str | int | float | bool):
        return value
    return repr(value)


def _truncate_text(value: str, limit: int) -> str:
    """Keep diagnostic log entries bounded."""
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return f"{value[:limit]}... [truncated {omitted} chars]"
