"""Tests for the Job Search Context Engine domain pack."""

from __future__ import annotations

import pytest

from app.core.context_engine.models import IngestionRequest, OwnerType
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.service import ContextEngineService
from app.core.context_engine.storage import InMemoryContextRepository
from app.domains.job_search import build_job_search_domain_pack
from app.domains.job_search.models import ARTIFACT_TYPE_IDS


def build_service() -> ContextEngineService:
    """Return an in-memory service with the job_search domain registered."""
    registry = DomainRegistry()
    registry.register_domain(build_job_search_domain_pack())
    return ContextEngineService(
        registry=registry,
        repository=InMemoryContextRepository(),
    )


def ingest(
    service: ContextEngineService,
    artifact_type_id: str,
    text: str,
) -> None:
    """Ingest one test artifact."""
    service.ingest_artifact(
        IngestionRequest(
            domain_id="job_search",
            artifact_type_id=artifact_type_id,
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="invite-1",
            title=artifact_type_id,
            text=text,
        )
    )


def test_job_search_domain_registers_expected_extensions() -> None:
    pack = build_job_search_domain_pack()

    assert pack.id == "job_search"
    assert [
        artifact_type.id for artifact_type in pack.artifact_types
    ] == ARTIFACT_TYPE_IDS
    assert [extractor.id for extractor in pack.extractors] == [
        "job-description-extractor",
        "resume-extractor",
        "interview-notes-extractor",
        "personal-story-extractor",
    ]
    assert [builder.id for builder in pack.perspective_builders] == [
        "role_fit",
        "interview_prep",
        "resume_positioning",
        "application_pipeline",
        "compensation_scope_risk",
    ]


def test_job_description_extraction_outputs_source_grounded_context() -> None:
    service = build_service()

    result = service.ingest_artifact(
        IngestionRequest(
            domain_id="job_search",
            artifact_type_id="job_description",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="invite-1",
            title="JD",
            text=(
                "Title: Staff Platform Engineer\n"
                "Company: Acme AI\n"
                "Responsibilities: lead zero to one agent infrastructure.\n"
                "Technologies: Python, Kubernetes, OpenAI, Oracle.\n"
                "Compensation range: $180k-$220k plus equity.\n"
                "Hybrid in New York.\n"
            ),
        )
    )

    signal_types = {signal.signal_type for signal in result.signals}
    assert {
        "role_title",
        "company",
        "seniority",
        "responsibility",
        "technology",
        "compensation",
        "location_constraint",
        "unusual_scope_indicator",
        "inferred_risk",
    }.issubset(signal_types)
    assert all(signal.source_links for signal in result.signals)
    assert all(
        link.artifact_id == result.artifact.id
        for signal in result.signals
        for link in signal.source_links
    )
    assert {item.item_type for item in result.actionable_items}.issuperset(
        {"prepare_interview_brief", "research_company", "clarify_scope"}
    )


def test_resume_interview_and_story_extractors_feed_perspectives() -> None:
    service = build_service()
    ingest(
        service,
        "resume",
        (
            "Acme Corp - Senior Engineer\n"
            "Led Kubernetes platform migration and improved deploy time by 45%.\n"
            "Built AI agents with Python and OpenAI for internal workflows.\n"
        ),
    )
    ingest(
        service,
        "interview_notes",
        (
            "Concern: needs deeper system design examples.\n"
            "Open question: how much on-call is expected?\n"
            "Next: prepare cloud architecture study plan.\n"
        ),
    )
    ingest(
        service,
        "personal_story",
        (
            "Situation: legacy platform blocked releases.\n"
            "I led a cross-functional redesign.\n"
            "Result: reduced incidents by 30%."
        ),
    )

    role_fit = service.build_perspective(
        domain_id="job_search",
        view_definition_id="role_fit",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="invite-1",
    )
    interview = service.build_perspective(
        domain_id="job_search",
        view_definition_id="interview_prep",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="invite-1",
    )

    assert [section.title for section in role_fit.sections] == [
        "Strong Matches",
        "Weak or Missing Evidence",
        "Risks",
        "Suggested Positioning",
        "Open Questions",
    ]
    assert role_fit.sections[0].evidence_links
    assert interview.sections[1].title == "Best Supporting Stories"
    assert "reduced incidents" in (interview.sections[1].content or "")


def test_invalid_job_search_artifact_type_is_rejected() -> None:
    service = build_service()

    with pytest.raises(ValueError, match="Artifact type"):
        ingest(service, "cover_letter", "Unsupported source.")
