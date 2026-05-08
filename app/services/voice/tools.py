"""Voice tool implementations and typed contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.services.tool_registry import ToolCategory, tool_decorator


# ---------------------------------------------------------------------------
# Input / output contracts
# ---------------------------------------------------------------------------


class EmployerSize(StrEnum):
    """Normalized company size buckets."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class PrimaryProblem(StrEnum):
    """Whether the employer's main challenge is hiring or retention."""

    HIRING = "hiring"
    RETENTION = "retention"
    BOTH = "both"
    UNCLEAR = "unclear"


class PartnershipStatus(StrEnum):
    """Current depth of employer relationships with schools or workforce orgs."""

    NONE = "none"
    INFORMAL = "informal"
    ACTIVE = "active"


class ManagerCapacity(StrEnum):
    """Whether managers have bandwidth to support interns or apprentices."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class WorkforceProgramExperience(StrEnum):
    """Prior experience running internships, apprenticeships, or workforce programs."""

    NONE = "none"
    SOME = "some"
    EXPERIENCED = "experienced"


class EndConversationInput(BaseModel):
    """No parameters — signals the agent is done and the session should close."""


class EndConversationOutput(BaseModel):
    """Acknowledgement returned to xAI before the backend closes the session."""

    status: str = "closing"


@tool_decorator(
    ToolCategory.READ_ONLY,
    description=(
        "Signal that the conversation has reached a natural conclusion "
        "and the session should close."
    ),
    prompt_instructions=(
        "Call end_conversation tool immediately after detecting that the user is all set, "
        "and you delivered final remarks "
        "(e.g. 'have a great day', 'take care', 'glad I could help', "
        "'I'm still here if you need anything'). "
        "This includes follow-up responses after an interruption. "
        "If you have just said goodbye or a closing phrase of any kind, "
        "call this tool — do not wait for further confirmation. "
    ),
    input_model=EndConversationInput,
    output_model=EndConversationOutput,
    is_terminal=True,
)
def end_conversation(
    input: EndConversationInput,  # noqa: A002
    tool_config: dict[str, Any],
) -> EndConversationOutput:
    """No-op implementation — closing is handled by the session loop."""
    return EndConversationOutput()


class RecordAnswerInput(BaseModel):
    """Record a question, the user's raw spoken response, and the derived interpretation."""

    question: str = Field(description="The question that was asked")
    user_response: str = Field(description="The user's actual spoken response")
    derived_answer: str = Field(
        description="How the model interpreted or normalized the response"
    )


class RecordAnswerOutput(BaseModel):
    """Acknowledgement that the answer was recorded."""

    status: str = "recorded"


@tool_decorator(
    ToolCategory.READ_ONLY,
    description=(
        "Record a specific question asked during the conversation, "
        "the user's actual spoken response, and your normalized interpretation of it."
    ),
    prompt_instructions=(
        "Call record_answer after each intake question once you have a clear response. "
        "Pass the exact question text, the user's spoken response verbatim, "
        "and your normalized interpretation (e.g. the enum value or derived fact)."
    ),
    input_model=RecordAnswerInput,
    output_model=RecordAnswerOutput,
)
def record_answer(
    input: RecordAnswerInput,  # noqa: A002
    tool_config: dict[str, Any],
) -> RecordAnswerOutput:
    """No-op — the frontend receives call details via a tool_call WebSocket event."""
    return RecordAnswerOutput()


class AssessEmployerReadinessInput(BaseModel):
    """Structured intake collected during the voice conversation."""

    company_size: str = Field(
        description="Organization size (e.g. 'small under 50', 'medium 50-200', 'large over 200')"
    )
    industry: str = Field(
        default="",
        description="Industry or sector the organization operates in",
    )
    primary_problem: PrimaryProblem = Field(
        description="Whether the main challenge is hiring new people or retaining existing employees"
    )
    partnership_status: PartnershipStatus = Field(
        description="Current relationship with schools, colleges, or workforce organizations"
    )
    manager_capacity: ManagerCapacity = Field(
        description="Whether managers have time and capacity to support interns or apprentices"
    )
    workforce_program_experience: WorkforceProgramExperience = Field(
        description="Prior experience running internships, apprenticeships, or workforce programs"
    )


class AssessEmployerReadinessOutput(BaseModel):
    """Concise, voice-ready recommendation grounded in workforce frameworks."""

    recommended_starting_point: str
    top_risk: str
    next_step: str
    voice_response: str = Field(
        description="Full spoken response the voice agent should read to the caller"
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

_DEFAULT_OUTCOMES: dict[str, dict[str, str]] = {
    "apprenticeship": {
        "starting_point": "formal apprenticeship program",
        "top_risk": "high coordination overhead without existing partnerships",
        "next_step": "register with a registered apprenticeship intermediary and identify one employer partner",
        "voice_response": (
            "Based on what you shared, your organization looks ready for a formal apprenticeship program. "
            "The main risk to watch is {top_risk}. "
            "The most important next step is to {next_step}."
        ),
    },
    "paid_internship": {
        "starting_point": "small paid internship pilot with one education partner",
        "top_risk": "manager bandwidth during peak periods",
        "next_step": "identify one school or college partner and define a clear intern role",
        "voice_response": (
            "Based on what you shared, I would start with a small paid internship pilot rather than a full apprenticeship. "
            "The main risk is {top_risk}. "
            "The most important next step is to {next_step}."
        ),
    },
    "job_shadowing": {
        "starting_point": "job shadowing or informational visits",
        "top_risk": "low visibility without consistent outreach",
        "next_step": "reach out to one local school or workforce organization to arrange an initial visit",
        "voice_response": (
            "Based on what you shared, I would begin with job shadowing before committing to a paid program. "
            "The main risk is {top_risk}. "
            "The most important next step is to {next_step}."
        ),
    },
    "retention_focus": {
        "starting_point": "retention and job quality improvements before adding new programs",
        "top_risk": "recruiting into a role with known turnover without fixing root causes",
        "next_step": "survey current employees to identify the top two reasons people leave",
        "voice_response": (
            "Based on what you shared, I would focus on retention before launching a new workforce program. "
            "The main risk of skipping this step is {top_risk}. "
            "The most important first action is to {next_step}."
        ),
    },
    "partnership_building": {
        "starting_point": "building one education partnership before scaling programs",
        "top_risk": "launching a program without a reliable talent pipeline",
        "next_step": "attend one local workforce convening or contact a community college workforce liaison",
        "voice_response": (
            "Based on what you shared, the most important thing right now is building your first education partnership. "
            "The main risk of moving too fast is {top_risk}. "
            "The most concrete next step is to {next_step}."
        ),
    },
}


@tool_decorator(
    ToolCategory.READ_ONLY,
    description=(
        "Assess an employer's workforce development readiness based on collected answers "
        "and return a concise, voice-ready recommendation grounded in workforce frameworks."
    ),
    prompt_instructions=(
        "Call assess_employer_readiness tool after you have collected company size, "
        "primary problem, partnership status, manager capacity, and workforce program "
        "experience. Read the voice_response field directly to the caller."
    ),
    input_model=AssessEmployerReadinessInput,
    output_model=AssessEmployerReadinessOutput,
)
def assess_employer_readiness(
    input: AssessEmployerReadinessInput,
    tool_config: dict[str, Any],
) -> AssessEmployerReadinessOutput:
    """Score employer readiness and return a voice-ready recommendation.

    Scoring rules are hardcoded defaults; tool_config may supply custom
    outcome overrides under the key 'outcomes'.
    """
    custom_outcomes: dict[str, dict[str, str]] = tool_config.get("outcomes", {})
    outcomes = {**_DEFAULT_OUTCOMES, **custom_outcomes}

    outcome_key = _select_outcome(
        primary_problem=input.primary_problem,
        partnership_status=input.partnership_status,
        manager_capacity=input.manager_capacity,
        workforce_program_experience=input.workforce_program_experience,
    )
    outcome = outcomes.get(outcome_key, outcomes["paid_internship"])

    voice_response = outcome["voice_response"].format(
        top_risk=outcome["top_risk"],
        next_step=outcome["next_step"],
    )

    return AssessEmployerReadinessOutput(
        recommended_starting_point=outcome["starting_point"],
        top_risk=outcome["top_risk"],
        next_step=outcome["next_step"],
        voice_response=voice_response,
    )


def _select_outcome(
    primary_problem: str,
    partnership_status: str,
    manager_capacity: str,
    workforce_program_experience: str,
) -> str:
    if primary_problem == PrimaryProblem.RETENTION:
        return "retention_focus"
    if (
        partnership_status == PartnershipStatus.NONE
        and workforce_program_experience == WorkforceProgramExperience.NONE
    ):
        return "partnership_building"
    if manager_capacity == ManagerCapacity.LOW:
        return (
            "job_shadowing"
            if partnership_status == PartnershipStatus.NONE
            else "paid_internship"
        )
    if (
        partnership_status == PartnershipStatus.ACTIVE
        and manager_capacity == ManagerCapacity.HIGH
        and workforce_program_experience == WorkforceProgramExperience.EXPERIENCED
    ):
        return "apprenticeship"
    if partnership_status in (
        PartnershipStatus.INFORMAL,
        PartnershipStatus.ACTIVE,
    ) and manager_capacity in (
        ManagerCapacity.MODERATE,
        ManagerCapacity.HIGH,
    ):
        return "paid_internship"
    return "job_shadowing"
