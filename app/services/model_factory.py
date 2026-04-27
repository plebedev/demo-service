"""Minimal provider/model abstraction for PydanticAI agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai.settings import ModelSettings

from app.core.config import Settings
from app.workflows.config_models import (
    AgentWorkflowConfig,
    PostProcessorConfig,
    WorkflowProvider,
)

if TYPE_CHECKING:  # pragma: no cover
    from pydantic_ai.models import Model


@dataclass(frozen=True)
class ProviderDefinition:
    """Provider construction details for the model factory."""

    env_var_name: str
    implemented: bool


PROVIDER_DEFINITIONS: dict[WorkflowProvider, ProviderDefinition] = {
    WorkflowProvider.OPENAI: ProviderDefinition(
        env_var_name="OPENAI_API_KEY", implemented=True
    ),
    WorkflowProvider.ANTHROPIC: ProviderDefinition(
        env_var_name="ANTHROPIC_API_KEY", implemented=True
    ),
    WorkflowProvider.FIREWORKS: ProviderDefinition(
        env_var_name="FIREWORKS_API_KEY", implemented=False
    ),
    WorkflowProvider.OPENROUTER: ProviderDefinition(
        env_var_name="OPENROUTER_API_KEY", implemented=False
    ),
}


def required_api_key_env_var(provider: WorkflowProvider) -> str:
    """Return the expected API-key environment variable for a provider."""
    return PROVIDER_DEFINITIONS[provider].env_var_name


def provider_is_implemented(provider: WorkflowProvider) -> bool:
    """Return whether runtime model creation is implemented for a provider."""
    return PROVIDER_DEFINITIONS[provider].implemented


def create_model(
    provider: WorkflowProvider, model_name: str, settings: Settings
) -> "Model":
    """Create a concrete PydanticAI model from config and environment settings."""
    if provider == WorkflowProvider.OPENAI:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI-configured agents.")
        return OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(api_key=settings.openai_api_key),
        )

    if provider == WorkflowProvider.ANTHROPIC:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        if not settings.anthropic_api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for Anthropic-configured agents."
            )
        return AnthropicModel(
            model_name,
            provider=AnthropicProvider(api_key=settings.anthropic_api_key),
        )

    env_var_name = required_api_key_env_var(provider)
    raise NotImplementedError(
        f"Provider '{provider.value}' is reserved for future milestones. "
        f"Configure {env_var_name} when runtime support is added."
    )


def build_model_settings(
    config: AgentWorkflowConfig | PostProcessorConfig,
) -> ModelSettings | None:
    """Convert YAML knobs into PydanticAI model settings."""
    if (
        config.temperature is None
        and config.max_tokens is None
        and config.timeout is None
    ):
        return None

    settings: ModelSettings = {}
    if config.temperature is not None:
        settings["temperature"] = config.temperature
    if config.max_tokens is not None:
        settings["max_tokens"] = config.max_tokens
    if config.timeout is not None:
        settings["timeout"] = config.timeout
    return settings
