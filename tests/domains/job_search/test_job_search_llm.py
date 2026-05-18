"""Tests for LLM-assisted job_search Context Engine behavior."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest
from pydantic import BaseModel

from app.core.context_engine.llm import (
    ContextExecutionContext,
    ContextExecutionMode,
    ContextModelFlowCatalog,
    ResolvedContextModelStep,
)
from app.core.context_engine.models import IngestionRequest, IngestionResult, OwnerType
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.service import ContextEngineService
from app.core.context_engine.storage import InMemoryContextRepository
from app.domains.job_search import build_job_search_domain_pack
from app.domains.job_search.llm import (
    LLMActionableItemOutput,
    LLMExtractionOutput,
    LLMPerspectiveOutput,
)

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class FakeContextModelRunner:
    """Fake structured runner for unit tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.prompts: list[dict[str, Any]] = []

    def run_structured(
        self,
        *,
        step: ResolvedContextModelStep,
        instructions: str,
        prompt: str,
        output_type: type[StructuredOutputT],
    ) -> StructuredOutputT:
        del instructions
        self.calls.append((step.flow_id, step.step_id))
        payload = json.loads(prompt)
        self.prompts.append(payload)
        chunks = payload.get("chunks", [])
        chunk = chunks[0]
        if output_type is LLMExtractionOutput:
            return cast(
                StructuredOutputT,
                LLMExtractionOutput.model_validate(
                    {
                        "signals": [
                            {
                                "title": "Strong generalist instincts",
                                "summary": "The role expects strong generalist instincts.",
                                "signal_type": "role_expectation",
                                "explicit_or_inferred": "explicit",
                                "confidence": "high",
                                "source_references": [
                                    {
                                        "chunk_id": chunk["id"],
                                        "excerpt": "Strong generalist instincts",
                                        "label": "role expectation",
                                    }
                                ],
                                "rationale": "The phrase appears in the job description.",
                            }
                        ],
                        "warnings": [],
                    }
                ),
            )
        if output_type is LLMPerspectiveOutput:
            return cast(
                StructuredOutputT,
                LLMPerspectiveOutput.model_validate(
                    {
                        "title": "Role Fit",
                        "sections": [
                            {
                                "id": "supported_requirements",
                                "title": "Supported Requirements",
                                "synthesized_conclusion": (
                                    "The current context has role expectations but no "
                                    "candidate evidence proving this one."
                                ),
                                "why_it_matters": (
                                    "The view should not turn job-description language "
                                    "into a user strength."
                                ),
                                "confidence": "high",
                                "evidence_references": [
                                    {
                                        "chunk_id": chunk["id"],
                                        "excerpt": "Strong generalist instincts",
                                        "label": "role expectation",
                                    }
                                ],
                                "actionable_implications": [
                                    "Add resume or story evidence before claiming this strength."
                                ],
                                "explicit_or_inferred": "inferred",
                                "rationale": "Only job-description evidence is present.",
                            }
                        ],
                    }
                ),
            )
        if output_type is LLMActionableItemOutput:
            return cast(
                StructuredOutputT,
                LLMActionableItemOutput.model_validate(
                    {
                        "actionable_items": [
                            {
                                "item_type": "add_supporting_evidence",
                                "title": "Add evidence for generalist claim",
                                "description": (
                                    "Add a resume bullet or story before positioning this "
                                    "as a user strength."
                                ),
                                "priority": "high",
                                "readiness_status": "needs_source_material",
                                "owner_type": "human",
                                "rationale": "The only current evidence is a job requirement.",
                                "evidence_links": [
                                    {
                                        "chunk_id": chunk["id"],
                                        "excerpt": "Strong generalist instincts",
                                        "label": "role expectation",
                                    }
                                ],
                            }
                        ]
                    }
                ),
            )
        raise AssertionError(f"Unexpected output type: {output_type}")


class BrokenContextModelRunner(FakeContextModelRunner):
    """Fake runner that simulates model/provider failure."""

    def run_structured(
        self,
        *,
        step: ResolvedContextModelStep,
        instructions: str,
        prompt: str,
        output_type: type[StructuredOutputT],
    ) -> StructuredOutputT:
        del step, instructions, prompt, output_type
        raise RuntimeError("model unavailable")


def build_catalog() -> ContextModelFlowCatalog:
    """Return test Context Engine flow config."""
    return ContextModelFlowCatalog.model_validate(
        {
            "default_mode": "hybrid",
            "default_model_profile": "fast",
            "model_profiles": {
                "fast": {
                    "provider": "openai",
                    "model": "configured-test-model",
                    "temperature": 0,
                    "structured_output": True,
                }
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
                            "prompt_template": "job_search/prompts/artifact_extraction.md",
                            "prompt_version": "test-v1",
                        }
                    ],
                },
                {
                    "domain_id": "job_search",
                    "flow_id": "perspective_synthesis",
                    "mode": "hybrid",
                    "steps": [
                        {
                            "id": "role_fit",
                            "purpose": "perspective_synthesis",
                            "prompt_template": "job_search/prompts/perspective_synthesis.md",
                            "prompt_version": "test-v1",
                        }
                    ],
                },
                {
                    "domain_id": "job_search",
                    "flow_id": "actionable_item_synthesis",
                    "mode": "hybrid",
                    "steps": [
                        {
                            "id": "actionable_items",
                            "purpose": "actionable_item_synthesis",
                            "prompt_template": "job_search/prompts/actionable_item_synthesis.md",
                            "prompt_version": "test-v1",
                        }
                    ],
                },
            ],
        }
    )


def build_service(
    runner: FakeContextModelRunner,
    mode: ContextExecutionMode = ContextExecutionMode.HYBRID,
) -> ContextEngineService:
    """Build an in-memory job_search service with fake LLM execution."""
    registry = DomainRegistry()
    registry.register_domain(build_job_search_domain_pack())
    return ContextEngineService(
        registry=registry,
        repository=InMemoryContextRepository(),
        execution_context=ContextExecutionContext(
            catalog=build_catalog(),
            runner=runner,
            prompt_root=Path("app/domains"),
            mode_override=mode,
        ),
    )


def ingest_generalist_job(service: ContextEngineService) -> IngestionResult:
    """Ingest a job description containing the regression phrase."""
    return service.ingest_artifact(
        IngestionRequest(
            domain_id="job_search",
            artifact_type_id="job_description",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="invite-llm",
            title="Generalist role",
            text=(
                "Title: Staff Product Engineer\n"
                "We need Strong generalist instincts and comfort with ambiguity.\n"
            ),
        )
    )


def test_llm_extraction_classifies_job_requirement_as_role_expectation() -> None:
    runner = FakeContextModelRunner()
    result = ingest_generalist_job(build_service(runner))

    llm_signals = [
        signal
        for signal in result.signals
        if signal.metadata.get("generated_by") == "llm"
    ]

    assert runner.calls[0] == ("extraction", "artifact_extraction")
    assert llm_signals
    assert llm_signals[0].signal_type == "role_expectation"
    assert llm_signals[0].metadata["explicit_or_inferred"] == "explicit"
    assert llm_signals[0].metadata["model_profile"] == "fast"
    assert "user_strength" not in {signal.signal_type for signal in result.signals}


def test_llm_perspective_uses_owner_scoped_context_and_preserves_grounding() -> None:
    runner = FakeContextModelRunner()
    service = build_service(runner)
    ingest_generalist_job(service)

    view = service.build_perspective(
        domain_id="job_search",
        view_definition_id="role_fit",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="invite-llm",
    )

    assert ("perspective_synthesis", "role_fit") in runner.calls
    assert view.metadata["generated_by"] == "llm"
    assert view.sections[0].metadata["confidence"] == "high"
    assert view.sections[0].evidence_links
    chunk_id = view.sections[0].evidence_links[0].source.chunk_id
    assert chunk_id is not None
    assert chunk_id.startswith("chunk_")
    assert "no candidate evidence" in (view.sections[0].content or "").lower()


def test_llm_perspective_prompt_uses_compact_ids_and_bounded_context() -> None:
    runner = FakeContextModelRunner()
    service = build_service(runner)
    ingest_generalist_job(service)

    service.build_perspective(
        domain_id="job_search",
        view_definition_id="role_fit",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="invite-llm",
    )

    perspective_prompt = next(
        prompt
        for flow, prompt in zip(
            (call[0] for call in runner.calls), runner.prompts, strict=True
        )
        if flow == "perspective_synthesis"
    )
    rendered = json.dumps(perspective_prompt)

    assert (
        re.search(r'"(?:id|artifact_id|chunk_id)": "(?:art|chunk)_', rendered) is None
    )
    assert perspective_prompt["chunks"][0]["id"] == "c1"
    assert "text" not in perspective_prompt["artifacts"][0]
    assert len(perspective_prompt["chunks"][0]["text"]) <= 900


def test_llm_actionable_items_include_rationale_and_readiness() -> None:
    runner = FakeContextModelRunner()
    result = ingest_generalist_job(build_service(runner))

    item = next(
        item
        for item in result.actionable_items
        if item.item_type == "add_supporting_evidence"
    )

    assert ("actionable_item_synthesis", "actionable_items") in runner.calls
    assert item.readiness_status.value == "needs_source_material"
    assert (
        item.metadata["rationale"] == "The only current evidence is a job requirement."
    )
    assert item.source_links


def test_llm_failure_falls_back_to_deterministic_output() -> None:
    result = ingest_generalist_job(build_service(BrokenContextModelRunner()))

    assert result.signals
    assert all(
        signal.metadata.get("generated_by") == "deterministic"
        for signal in result.signals
    )
    assert any(
        "llm_failed" in signal.metadata.get("fallback_warning", "")
        for signal in result.signals
    )


def test_deterministic_mode_skips_fake_model_runner() -> None:
    runner = FakeContextModelRunner()
    result = ingest_generalist_job(
        build_service(runner, mode=ContextExecutionMode.DETERMINISTIC)
    )

    assert runner.calls == []
    assert result.signals
    assert all(
        signal.metadata.get("generated_by") == "deterministic"
        for signal in result.signals
    )


def test_ungrounded_llm_claim_is_rejected_and_falls_back() -> None:
    class UngroundedRunner(FakeContextModelRunner):
        def run_structured(
            self,
            *,
            step: ResolvedContextModelStep,
            instructions: str,
            prompt: str,
            output_type: type[StructuredOutputT],
        ) -> StructuredOutputT:
            del step, instructions, prompt, output_type
            return cast(
                StructuredOutputT,
                LLMExtractionOutput.model_validate(
                    {
                        "signals": [
                            {
                                "title": "Invented strength",
                                "summary": "Candidate is a strong generalist.",
                                "signal_type": "user_strength",
                                "explicit_or_inferred": "inferred",
                                "confidence": "high",
                                "source_references": [
                                    {
                                        "chunk_id": "missing-chunk",
                                        "excerpt": "not in provided chunks",
                                    }
                                ],
                                "rationale": "Unsupported.",
                            }
                        ]
                    }
                ),
            )

    result = ingest_generalist_job(build_service(UngroundedRunner()))

    assert "user_strength" not in {signal.signal_type for signal in result.signals}
    assert any(
        "Unknown source chunk" in signal.metadata.get("fallback_warning", "")
        for signal in result.signals
    )
