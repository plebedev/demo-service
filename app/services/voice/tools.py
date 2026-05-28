"""Voice tool implementations and typed contracts."""

from __future__ import annotations

from enum import StrEnum
import json
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.tool_registry import ToolCategory, tool_decorator

logger = logging.getLogger(__name__)


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


class PrepareMeetingContextInput(BaseModel):
    """Meeting details used to prepare model-generated discussion context."""

    company_name: str = Field(description="Company or organization name")
    meeting_purpose: str = Field(
        description="Purpose of the meeting, such as partnership discussion"
    )
    user_role: str = Field(
        default="",
        description="Optional role or perspective of the caller",
    )
    desired_outcome: str = Field(
        default="",
        description="Optional outcome the caller wants from the meeting",
    )


class PrepareMeetingContextOutput(BaseModel):
    """Structured, voice-ready meeting prep context."""

    company_name: str
    meeting_purpose: str
    summary: str
    talking_points: list[str]
    watchout: str
    recommended_next_question: str
    limitations: str


class WarmTransferCallInput(BaseModel):
    """Transfer target provided by the caller during a live voice session."""

    transfer_to_phone_number: str = Field(
        description=(
            "Phone number to transfer to, in strict E.164 format "
            "(example: +16177100171)."
        ),
        pattern=r"^\+[1-9]\d{1,14}$",
    )


class WarmTransferCallOutput(BaseModel):
    """Status payload returned after invoking the SBC transfer control API."""

    status: str = Field(
        description="Transfer submission status: 'started' when accepted, else 'failed'."
    )
    session_id: str | None = Field(
        default=None,
        description="Active call session identifier used for transfer routing.",
    )
    transfer_to_phone_number: str = Field(
        description="Validated E.164 number that the transfer attempted to dial."
    )
    message: str = Field(
        description="Human-readable outcome message for transcript logging."
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

_MEETING_PREP_SYSTEM_PROMPT = (
    "You prepare concise meeting guidance for a voice assistant demo. "
    "Do not browse the web, imply live lookup, cite sources, or claim current facts. "
    "Use only the company name, meeting purpose, caller details, and general model "
    "knowledge. Frame company-specific content as unverified background or plausible "
    "preparation hypotheses. Return strict JSON with keys: summary, talking_points, "
    "watchout, recommended_next_question."
)

_MEETING_PREP_LIMITATIONS = (
    "This meeting prep does not browse the web, verify current company facts, "
    "or use private account data. It uses the details provided in the conversation "
    "plus general model knowledge, so treat the guidance as preparation hypotheses "
    "rather than live research."
)


@tool_decorator(
    ToolCategory.READ_ONLY,
    description=(
        "Prepare meeting context from the company name and meeting purpose without "
        "live web lookup, current-fact verification, or source-link claims."
    ),
    prompt_instructions=(
        "Call prepare_meeting_context after the user names the company and meeting "
        "purpose. Tell the user you are preparing context from what they shared and "
        "general background knowledge, not looking it up live. While the result is "
        "pending, continue asking useful generic meeting-prep questions. When the "
        "result arrives, begin with 'I got the results for...' and ask the "
        "recommended next question."
    ),
    input_model=PrepareMeetingContextInput,
    output_model=PrepareMeetingContextOutput,
)
def prepare_meeting_context(
    input: PrepareMeetingContextInput,  # noqa: A002
    tool_config: dict[str, Any],
) -> PrepareMeetingContextOutput:
    """Generate meeting prep context without live lookup or freshness claims."""
    settings = get_settings()
    started_at = time.monotonic()
    try:
        generated = _generate_meeting_prep_context(input, tool_config)
    except Exception:
        logger.exception("Meeting prep context generation failed")
        generated = _fallback_meeting_context(input)

    min_delay = float(
        tool_config.get(
            "min_delay_seconds",
            settings.voice_meeting_prep_min_delay_seconds,
        )
    )
    remaining_delay = min_delay - (time.monotonic() - started_at)
    if remaining_delay > 0:
        time.sleep(remaining_delay)

    fallback = _fallback_meeting_context(input)
    talking_points = [
        str(item).strip()
        for item in generated.get("talking_points", [])
        if str(item).strip()
    ][:4]

    return PrepareMeetingContextOutput(
        company_name=input.company_name,
        meeting_purpose=input.meeting_purpose,
        summary=str(generated.get("summary", "")).strip() or fallback["summary"],
        talking_points=talking_points or fallback["talking_points"],
        watchout=str(generated.get("watchout", "")).strip() or fallback["watchout"],
        recommended_next_question=str(
            generated.get("recommended_next_question", "")
        ).strip()
        or fallback["recommended_next_question"],
        limitations=_MEETING_PREP_LIMITATIONS,
    )


@tool_decorator(
    ToolCategory.MUTATIVE,
    description=(
        "Start a warm transfer by instructing the internal Rust SBC gateway to "
        "dial a destination phone number over the configured Twilio SIP trunk."
    ),
    prompt_instructions=(
        "Call warm_transfer_call when the caller explicitly asks to be transferred "
        "to a person. Pass only a strict E.164 number (starts with + and country "
        "code). Confirm the number with the caller before calling this tool."
    ),
    input_model=WarmTransferCallInput,
    output_model=WarmTransferCallOutput,
)
def warm_transfer_call(
    input: WarmTransferCallInput,  # noqa: A002
    tool_config: dict[str, Any],
) -> WarmTransferCallOutput:
    """Trigger a warm transfer via the Rust SBC control API."""
    transfer_cfg = _load_warm_transfer_config(tool_config)
    session_id = transfer_cfg["session_id"]
    if not session_id:
        return WarmTransferCallOutput(
            status="failed",
            session_id=None,
            transfer_to_phone_number=input.transfer_to_phone_number,
            message=(
                "Warm transfer is not available because no active call session id "
                "was found in runtime context."
            ),
        )

    missing = [
        key
        for key in ("gateway_base_url", "trunk_host", "twilio_number")
        if not transfer_cfg[key]
    ]
    if missing:
        return WarmTransferCallOutput(
            status="failed",
            session_id=session_id,
            transfer_to_phone_number=input.transfer_to_phone_number,
            message=(
                "Warm transfer tool is missing required configuration keys: "
                + ", ".join(missing)
            ),
        )

    payload = {
        "session_id": session_id,
        "target_phone": input.transfer_to_phone_number,
        "twilio_number": transfer_cfg["twilio_number"],
        "trunk_host": transfer_cfg["trunk_host"],
        "trunk_port": transfer_cfg["trunk_port"],
    }

    if transfer_cfg["rtp_target_host"] and transfer_cfg["rtp_target_port"]:
        payload["rtp_target_host"] = transfer_cfg["rtp_target_host"]
        payload["rtp_target_port"] = transfer_cfg["rtp_target_port"]

    transfer_url = (
        f"{str(transfer_cfg['gateway_base_url']).rstrip('/')}"
        "/api/internal/transfer/start"
    )
    timeout_seconds = float(transfer_cfg["timeout_seconds"])

    try:
        response = httpx.post(transfer_url, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
    except Exception as exc:
        logger.exception(
            "warm_transfer_call failed: session_id=%s target=%s",
            session_id,
            input.transfer_to_phone_number,
        )
        return WarmTransferCallOutput(
            status="failed",
            session_id=session_id,
            transfer_to_phone_number=input.transfer_to_phone_number,
            message=f"Warm transfer request failed: {exc}",
        )

    return WarmTransferCallOutput(
        status="started",
        session_id=session_id,
        transfer_to_phone_number=input.transfer_to_phone_number,
        message=(
            "Warm transfer request accepted by SBC gateway; outbound dialing has "
            "started."
        ),
    )


def _generate_meeting_prep_context(
    input: PrepareMeetingContextInput,
    tool_config: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    provider = str(
        tool_config.get("provider", settings.voice_meeting_prep_provider)
    ).lower()
    model = str(tool_config.get("model", settings.voice_meeting_prep_model))
    prompt = (
        f"Company: {input.company_name}\n"
        f"Meeting purpose: {input.meeting_purpose}\n"
        f"Caller role: {input.user_role or 'Not provided'}\n"
        f"Desired outcome: {input.desired_outcome or 'Not provided'}"
    )

    if provider == "openai":
        from openai import OpenAI

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY required for meeting prep context")
        openai_client = OpenAI(api_key=settings.openai_api_key)
        response = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _MEETING_PREP_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        parsed: dict[str, Any] = json.loads(content)
        return parsed

    if provider == "anthropic":
        from anthropic import Anthropic

        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY required for meeting prep context")
        anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
        anthropic_response = anthropic_client.messages.create(
            model=model,
            system=_MEETING_PREP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        block = anthropic_response.content[0]
        content = getattr(block, "text", "{}")
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
        return _fallback_meeting_context(input)

    raise ValueError(f"Unsupported meeting prep provider: {provider}")


def _fallback_meeting_context(
    input: PrepareMeetingContextInput,
) -> dict[str, Any]:
    return {
        "summary": (
            f"Prepare for {input.company_name} by connecting the conversation "
            f"directly to {input.meeting_purpose} and confirming what success "
            "would look like for both sides."
        ),
        "talking_points": [
            "Open with the meeting purpose and the outcome the user wants.",
            "Ask what constraints, stakeholders, and timing matter most.",
            "Frame any company-specific angle as a hypothesis to confirm.",
        ],
        "watchout": (
            "Avoid treating general model knowledge as verified current company news."
        ),
        "recommended_next_question": (
            "What would make this meeting feel successful when it ends?"
        ),
    }


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


def _load_warm_transfer_config(tool_config: dict[str, Any]) -> dict[str, Any]:
    """Load warm-transfer settings from persona config plus runtime context."""
    warm_transfer_cfg = tool_config.get("warm_transfer")
    if not isinstance(warm_transfer_cfg, dict):
        warm_transfer_cfg = {}

    runtime = tool_config.get("_runtime")
    if not isinstance(runtime, dict):
        runtime = {}

    return {
        "gateway_base_url": str(
            warm_transfer_cfg.get(
                "gateway_base_url",
                tool_config.get("gateway_base_url", ""),
            )
        ).strip(),
        "trunk_host": str(
            warm_transfer_cfg.get("trunk_host", tool_config.get("trunk_host", ""))
        ).strip(),
        "twilio_number": str(
            warm_transfer_cfg.get(
                "twilio_number",
                tool_config.get("twilio_number", ""),
            )
        ).strip(),
        "trunk_port": _coerce_int(
            warm_transfer_cfg.get("trunk_port", tool_config.get("trunk_port", 5060)),
            fallback=5060,
        ),
        "timeout_seconds": _coerce_float(
            warm_transfer_cfg.get(
                "timeout_seconds",
                tool_config.get("timeout_seconds", 5.0),
            ),
            fallback=5.0,
        ),
        "rtp_target_host": str(
            warm_transfer_cfg.get(
                "rtp_target_host",
                tool_config.get("rtp_target_host", ""),
            )
        ).strip(),
        "rtp_target_port": warm_transfer_cfg.get(
            "rtp_target_port",
            tool_config.get("rtp_target_port"),
        ),
        "session_id": str(
            runtime.get("session_id")
            or warm_transfer_cfg.get("session_id")
            or tool_config.get("session_id", "")
        ).strip(),
    }


def _coerce_int(value: Any, *, fallback: int) -> int:
    """Parse int-like values from JSON tool config with a safe fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_float(value: Any, *, fallback: float) -> float:
    """Parse float-like values from JSON tool config with a safe fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
