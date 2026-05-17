"""Domain-pack registration for Job Search / Career Context."""

from __future__ import annotations

from app.core.context_engine.interfaces import DomainPack, ViewDefinition
from app.core.context_engine.models import ArtifactType
from app.domains.job_search.extractors import (
    InterviewNotesExtractor,
    JobDescriptionExtractor,
    PersonalStoryExtractor,
    ResumeExtractor,
)
from app.domains.job_search.models import ARTIFACT_TYPE_IDS, DOMAIN_ID
from app.domains.job_search.perspectives import (
    ApplicationPipelinePerspectiveBuilder,
    CompensationScopeRiskPerspectiveBuilder,
    InterviewPrepPerspectiveBuilder,
    ResumePositioningPerspectiveBuilder,
    RoleFitPerspectiveBuilder,
)
from app.domains.job_search.task_generators import JobSearchTaskGenerator


ARTIFACT_DISPLAY_NAMES = {
    "job_description": "Job Description",
    "resume": "Resume",
    "recruiter_message": "Recruiter Message",
    "interview_notes": "Interview Notes",
    "company_research": "Company Research",
    "personal_story": "Personal Story",
    "compensation_notes": "Compensation Notes",
    "follow_up_notes": "Follow-Up Notes",
}


def build_job_search_domain_pack() -> DomainPack:
    """Build the first real Context Engine domain pack."""
    return DomainPack(
        id=DOMAIN_ID,
        display_name="Job Search / Career Context",
        artifact_types=[
            ArtifactType(
                id=artifact_type_id,
                display_name=ARTIFACT_DISPLAY_NAMES[artifact_type_id],
                description=(
                    "Career-context source material registered by the job_search "
                    "domain pack."
                ),
                accepted_mime_types=["text/plain", "application/pdf"],
            )
            for artifact_type_id in ARTIFACT_TYPE_IDS
        ],
        extractors=[
            JobDescriptionExtractor(),
            ResumeExtractor(),
            InterviewNotesExtractor(),
            PersonalStoryExtractor(),
        ],
        perspective_builders=[
            RoleFitPerspectiveBuilder(),
            InterviewPrepPerspectiveBuilder(),
            ResumePositioningPerspectiveBuilder(),
            ApplicationPipelinePerspectiveBuilder(),
            CompensationScopeRiskPerspectiveBuilder(),
        ],
        task_generators=[JobSearchTaskGenerator()],
        view_definitions=[
            ViewDefinition(
                id="role_fit",
                display_name="Role Fit",
                description="Source-grounded fit, evidence gaps, risks, and positioning.",
            ),
            ViewDefinition(
                id="interview_prep",
                display_name="Interview Prep",
                description="Interview themes, supporting stories, topics, and concerns.",
            ),
            ViewDefinition(
                id="resume_positioning",
                display_name="Resume Positioning",
                description="Resume evidence and rewrite suggestions.",
            ),
            ViewDefinition(
                id="application_pipeline",
                display_name="Application Pipeline",
                description="Opportunities, next actions, blockers, and follow-ups.",
            ),
            ViewDefinition(
                id="compensation_scope_risk",
                display_name="Compensation and Scope Risk",
                description="Compensation signals, scope risk, and judgment areas.",
            ),
        ],
        metadata={
            "domain_pack": "job_search",
            "status": "mvp",
            "source_grounded": True,
            "unsupported_inputs": ["images", "OCR", "audio", "video", "web lookup"],
        },
    )
