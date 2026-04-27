"""Phase-1 guardrails shared across invite-gated demo endpoints."""

from pydantic import BaseModel

from app.core.config import Settings


class Phase1Limits(BaseModel):
    """Documented hard limits for the phase-1 demo."""

    max_files_per_run: int
    max_file_size_bytes: int
    max_extracted_text_bytes: int
    max_total_workflow_text_bytes: int


class Phase1FollowUpPolicy(BaseModel):
    """Follow-up constraints for phase-1 brief generation."""

    generated_briefs_per_run: int
    max_follow_up_questions: int
    follow_up_scope: str
    requires_new_run_after_follow_up: bool


class Phase1Guardrails(BaseModel):
    """Structured summary of the current demo constraints."""

    demo_only: bool
    supported_inputs: list[str]
    unsupported_inputs: list[str]
    limits: Phase1Limits
    follow_up_policy: Phase1FollowUpPolicy


def build_phase1_guardrails(settings: Settings) -> Phase1Guardrails:
    """Return the phase-1 guardrails visible to the UI and future workflows."""
    return Phase1Guardrails(
        demo_only=True,
        supported_inputs=[
            "pasted text",
            "text file upload",
            "PDF upload with extractable text",
        ],
        unsupported_inputs=[
            "images",
            "OCR",
            "audio/video",
            "web lookup",
        ],
        limits=Phase1Limits(
            max_files_per_run=settings.max_files_per_run,
            max_file_size_bytes=settings.max_file_size_bytes,
            max_extracted_text_bytes=settings.max_extracted_text_bytes,
            max_total_workflow_text_bytes=settings.max_total_workflow_text_bytes,
        ),
        follow_up_policy=Phase1FollowUpPolicy(
            generated_briefs_per_run=1,
            max_follow_up_questions=1,
            follow_up_scope="Follow-up must be about the generated brief.",
            requires_new_run_after_follow_up=True,
        ),
    )


def workflow_guardrail_todo() -> str:
    """Return the next implementation boundary for future workflow ingestion."""
    return (
        "TODO: apply these phase-1 input and follow-up limits at the real workflow "
        "ingestion and brief-generation endpoints when that flow is implemented."
    )
