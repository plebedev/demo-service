"""Tests for generic Context Engine model flow configuration."""

from __future__ import annotations

import pytest

from app.core.context_engine.llm import (
    ContextExecutionMode,
    ContextModelFlowCatalog,
)


def catalog() -> ContextModelFlowCatalog:
    """Return a small model-flow catalog."""
    return ContextModelFlowCatalog.model_validate(
        {
            "default_mode": "hybrid",
            "default_model_profile": "fast",
            "model_profiles": {
                "fast": {
                    "provider": "openai",
                    "model": "configured-fast-model",
                    "temperature": 0,
                    "structured_output": True,
                },
                "strong": {
                    "provider": "anthropic",
                    "model": "configured-strong-model",
                    "temperature": 0,
                    "structured_output": True,
                },
            },
            "flows": [
                {
                    "domain_id": "job_search",
                    "flow_id": "extraction",
                    "mode": "hybrid",
                    "steps": [
                        {
                            "id": "artifact_extraction",
                            "purpose": "structured_extraction",
                            "model_profile": "fast",
                            "prompt_template": "job_search/prompts/artifact.md",
                            "prompt_version": "v1",
                        }
                    ],
                },
                {
                    "domain_id": "job_search",
                    "flow_id": "perspective_synthesis",
                    "mode": "llm",
                    "model_profile": "strong",
                    "steps": [
                        {
                            "id": "role_fit",
                            "purpose": "perspective_synthesis",
                            "prompt_template": "job_search/prompts/perspective.md",
                            "prompt_version": "v1",
                        }
                    ],
                },
            ],
        }
    )


def test_model_profile_lookup_by_domain_flow_step_and_purpose() -> None:
    step = catalog().resolve_step(
        domain_id="job_search",
        flow_id="perspective_synthesis",
        step_id="role_fit",
        purpose="perspective_synthesis",
    )

    assert step.mode == ContextExecutionMode.LLM
    assert step.model_profile_id == "strong"
    assert step.model_profile.model == "configured-strong-model"


def test_missing_config_fails_clearly() -> None:
    with pytest.raises(ValueError, match="No Context Engine model flow"):
        catalog().resolve_step(
            domain_id="missing",
            flow_id="extraction",
            step_id="artifact_extraction",
        )

    with pytest.raises(ValueError, match="No Context Engine model step"):
        catalog().resolve_step(
            domain_id="job_search",
            flow_id="extraction",
            step_id="missing",
        )


def test_execution_mode_override_supports_deterministic_llm_and_hybrid() -> None:
    flow_catalog = catalog()

    for mode in ContextExecutionMode:
        step = flow_catalog.resolve_step(
            domain_id="job_search",
            flow_id="extraction",
            step_id="artifact_extraction",
            mode_override=mode,
        )
        assert step.mode == mode
