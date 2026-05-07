"""Minimal provider/model abstraction for PydanticAI agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai import ModelSettings

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


def create_provider_model_settings(
    *,
    provider: WorkflowProvider,
    timeout: float | None,
    temperature: float | None,
    max_tokens: int | None,
) -> ModelSettings | None:
    """Create provider-specific PydanticAI model settings.

    Anthropic prompt caching is required for configured Anthropic workflows.
    OpenAI prompt caching is handled by the provider for eligible prompt prefixes,
    so OpenAI only receives the generic runtime knobs configured in YAML.
    """
    if provider == WorkflowProvider.ANTHROPIC:
        from pydantic_ai.models.anthropic import AnthropicModelSettings

        anthropic_settings: AnthropicModelSettings = {
            "anthropic_cache_instructions": True,
            "anthropic_cache_tool_definitions": True,
            "anthropic_cache_messages": True,
        }
        if temperature is not None:
            anthropic_settings["temperature"] = temperature
        if max_tokens is not None:
            anthropic_settings["max_tokens"] = max_tokens
        if timeout is not None:
            anthropic_settings["timeout"] = timeout
        return anthropic_settings

    if temperature is None and max_tokens is None and timeout is None:
        return None

    settings: ModelSettings = {}
    if temperature is not None:
        settings["temperature"] = temperature
    if max_tokens is not None:
        settings["max_tokens"] = max_tokens
    if timeout is not None:
        settings["timeout"] = timeout
    return settings


def create_model_settings(
    config: AgentWorkflowConfig | PostProcessorConfig,
) -> ModelSettings | None:
    """Create model settings from YAML workflow configuration."""
    return create_provider_model_settings(
        provider=config.provider,
        timeout=config.timeout,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )


def build_model_settings(
    config: AgentWorkflowConfig | PostProcessorConfig,
) -> ModelSettings | None:
    """Backward-compatible wrapper for provider-specific model settings."""
    return create_model_settings(config)
