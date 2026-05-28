"""Domain-pack registration for Job Search / Career Context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from app.core.context_engine.interfaces import DomainPack, ViewDefinition
from app.core.context_engine.models import ArtifactType
from app.domains.job_search.extractors import (
    CareerContextNotesExtractor,
    InterviewNotesExtractor,
    JobDescriptionExtractor,
    PersonalStoryExtractor,
    ResumeExtractor,
)
from app.domains.job_search.llm import (
    LLMAssistedExtractor,
    LLMAssistedPerspectiveBuilder,
    LLMAssistedTaskGenerator,
    PerspectiveContextGraph,
)
from app.domains.job_search.perspectives import (
    ApplicationPipelinePerspectiveBuilder,
    CompensationScopeRiskPerspectiveBuilder,
    InterviewPrepPerspectiveBuilder,
    ResumePositioningPerspectiveBuilder,
    RoleFitPerspectiveBuilder,
)
from app.domains.job_search.task_generators import JobSearchTaskGenerator


DOMAIN_MANIFEST_PATH = Path(__file__).with_name("domain.yaml")


def _load_manifest() -> dict[str, Any]:
    """Load the domain manifest used as registration metadata."""
    with DOMAIN_MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
        payload = yaml.safe_load(manifest_file)
    if not isinstance(payload, dict):
        raise ValueError("Job Search domain manifest must be a mapping.")
    return payload


def build_job_search_domain_pack() -> DomainPack:
    """Build the first real Context Engine domain pack."""
    manifest = _load_manifest()
    artifact_type_entries = manifest.get("artifact_types", [])
    if not isinstance(artifact_type_entries, list):
        raise ValueError("Job Search domain manifest artifact_types must be a list.")
    view_entries = manifest.get("views", [])
    if not isinstance(view_entries, list):
        raise ValueError("Job Search domain manifest views must be a list.")
    accepted_mime_types = list(manifest.get("accepted_mime_types", []))
    return DomainPack(
        id=str(manifest["id"]),
        display_name=str(manifest["display_name"]),
        artifact_types=[
            ArtifactType(
                id=str(entry["id"]),
                display_name=str(entry["display_name"]),
                description=(
                    "Career-context source material registered by the job_search "
                    "domain pack."
                ),
                accepted_mime_types=accepted_mime_types,
                metadata={"extractor_ids": list(entry.get("extractor_ids", []))},
            )
            for entry in artifact_type_entries
        ],
        extractors=[
            LLMAssistedExtractor(JobDescriptionExtractor()),
            LLMAssistedExtractor(ResumeExtractor()),
            LLMAssistedExtractor(InterviewNotesExtractor()),
            LLMAssistedExtractor(PersonalStoryExtractor()),
            LLMAssistedExtractor(CareerContextNotesExtractor()),
        ],
        perspective_builders=[
            LLMAssistedPerspectiveBuilder(
                RoleFitPerspectiveBuilder(),
                _context_graph_for_view(view_entries, "role_fit"),
            ),
            LLMAssistedPerspectiveBuilder(
                InterviewPrepPerspectiveBuilder(),
                _context_graph_for_view(view_entries, "interview_prep"),
            ),
            LLMAssistedPerspectiveBuilder(
                ResumePositioningPerspectiveBuilder(),
                _context_graph_for_view(view_entries, "resume_positioning"),
            ),
            LLMAssistedPerspectiveBuilder(
                ApplicationPipelinePerspectiveBuilder(),
                _context_graph_for_view(view_entries, "application_pipeline"),
            ),
            LLMAssistedPerspectiveBuilder(
                CompensationScopeRiskPerspectiveBuilder(),
                _context_graph_for_view(view_entries, "compensation_scope_risk"),
            ),
        ],
        task_generators=[LLMAssistedTaskGenerator(JobSearchTaskGenerator())],
        view_definitions=[
            ViewDefinition(
                id=str(entry["id"]),
                display_name=str(entry["display_name"]),
                description=(
                    str(entry["description"]) if entry.get("description") else None
                ),
                metadata={
                    "context_dependency_graph": entry.get("context", {}),
                },
            )
            for entry in view_entries
        ],
        metadata={
            "domain_pack": str(manifest["id"]),
            "status": str(manifest.get("status", "mvp")),
            "source_grounded": bool(manifest.get("source_grounded", True)),
            "execution_modes": ["deterministic", "llm", "hybrid"],
            "llm_assisted": True,
            "unsupported_inputs": list(manifest.get("unsupported_inputs", [])),
            "extractor_routing": {
                str(entry["id"]): list(entry.get("extractor_ids", []))
                for entry in artifact_type_entries
            },
        },
    )


def _context_graph_for_view(
    view_entries: list[Any], view_id: str
) -> PerspectiveContextGraph:
    """Load declarative context dependencies for one view."""
    entry = next(
        (
            candidate
            for candidate in view_entries
            if isinstance(candidate, dict) and candidate.get("id") == view_id
        ),
        None,
    )
    if entry is None:
        raise ValueError(f"Job Search view '{view_id}' is not configured.")
    if "context" not in entry:
        raise ValueError(f"Job Search view '{view_id}' is missing context graph.")
    graph = PerspectiveContextGraph.model_validate(entry["context"])
    graph.require_node_types("signals")
    graph.require_node_types("actionable_items")
    return graph
