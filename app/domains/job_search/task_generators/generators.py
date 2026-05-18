"""Actionable-item generators for the Job Search domain pack."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ReadinessStatus,
    SourceLink,
)


def _source(artifact: Artifact) -> SourceLink:
    return SourceLink(
        artifact_id=artifact.id,
        label=artifact.artifact_type_id,
        excerpt=artifact.text[:500],
    )


@dataclass(frozen=True)
class JobSearchTaskGenerator:
    """Generate generic next actions from ingested career artifacts."""

    id: str = "job-search-task-generator"

    def generate(self, artifact: Artifact) -> list[ActionableItem]:
        """Generate source-grounded actionable items for one artifact."""
        source = _source(artifact)
        items: list[ActionableItem] = []
        if artifact.artifact_type_id == "job_description":
            items.extend(
                [
                    ActionableItem(
                        item_type="prepare_interview_brief",
                        title="Prepare interview brief",
                        description=(
                            "Summarize role requirements, likely themes, risks, and "
                            "source-grounded questions before the next conversation."
                        ),
                        readiness_status=ReadinessStatus.NEEDS_REVIEW,
                        source_links=[source],
                    ),
                    ActionableItem(
                        item_type="research_company_concerns",
                        title="Research company concerns",
                        description=(
                            "Add company research notes if the current source does not "
                            "explain the business, market, or team context."
                        ),
                        readiness_status=ReadinessStatus.NEEDS_SOURCE_MATERIAL,
                        source_links=[source],
                    ),
                ]
            )
        if artifact.artifact_type_id == "resume":
            items.append(
                ActionableItem(
                    item_type="rewrite_resume_section",
                    title="Rewrite resume section",
                    description=(
                        "Tune resume bullets toward the role using only existing "
                        "source-grounded skills, outcomes, and leadership evidence."
                    ),
                    readiness_status=ReadinessStatus.NEEDS_REVIEW,
                    source_links=[source],
                )
            )
        if artifact.artifact_type_id == "recruiter_message":
            items.append(
                ActionableItem(
                    item_type="draft_recruiter_follow_up",
                    title="Draft recruiter follow-up",
                    description=(
                        "Prepare a concise response that clarifies process, scope, "
                        "location, and compensation boundaries."
                    ),
                    readiness_status=ReadinessStatus.READY_FOR_AGENT,
                    source_links=[source],
                )
            )
        if artifact.artifact_type_id in {"compensation_notes", "job_description"}:
            items.append(
                ActionableItem(
                    item_type="clarify_compensation_expectations",
                    title="Clarify compensation expectations",
                    description=(
                        "Decide the minimum, target, and tradeoff boundaries before "
                        "delegating any outreach."
                    ),
                    readiness_status=ReadinessStatus.NEEDS_DECISION,
                    source_links=[source],
                )
            )
        if artifact.artifact_type_id == "interview_notes":
            items.append(
                ActionableItem(
                    item_type="prepare_architecture_story",
                    title="Prepare architecture story",
                    description=(
                        "Select a source-grounded story that answers the strongest "
                        "technical or leadership concern in the notes."
                    ),
                    readiness_status=ReadinessStatus.NEEDS_HUMAN_CLARIFICATION,
                    source_links=[source],
                )
            )
        if artifact.artifact_type_id == "company_research":
            items.append(
                ActionableItem(
                    item_type="research_company_concerns",
                    title="Research company concerns",
                    description=(
                        "Turn the captured company notes into grounded questions for "
                        "the next conversation."
                    ),
                    readiness_status=ReadinessStatus.READY_FOR_AGENT,
                    source_links=[source],
                )
            )
        if artifact.artifact_type_id == "follow_up_notes":
            items.append(
                ActionableItem(
                    item_type="draft_recruiter_follow_up",
                    title="Draft follow-up from notes",
                    readiness_status=ReadinessStatus.READY_FOR_AGENT,
                    source_links=[source],
                )
            )
        if not items:
            items.append(
                ActionableItem(
                    item_type="prepare_interview_brief",
                    title="Review source artifact",
                    readiness_status=ReadinessStatus.BLOCKED,
                    source_links=[source],
                )
            )
        return items
