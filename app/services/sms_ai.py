"""Bounded LLM helpers for SMS replies and opt-out classification."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from app.core.config import Settings
from app.models.run import Run


class OptOutClassification(BaseModel):
    """LLM output for unsubscribe-intent detection."""

    is_opt_out: bool
    reason: str


class SmsReply(BaseModel):
    """LLM output for concise SMS replies."""

    body: str


async def classify_opt_out_with_llm(
    message_body: str, settings: Settings
) -> OptOutClassification:
    """Classify whether an inbound message asks to stop future SMS."""
    from app.services.model_factory import create_model
    from app.workflows.config_models import WorkflowProvider

    provider = WorkflowProvider(settings.sms_reply_provider)
    model = create_model(provider, settings.sms_reply_model, settings)
    agent = Agent(
        model=model,
        instructions=(
            "Classify whether this SMS message expresses unsubscribe, opt-out, "
            "do-not-contact, or stop-texting intent. Be conservative: only mark "
            "true when the sender clearly wants future SMS stopped."
        ),
        output_type=OptOutClassification,
        model_settings={"temperature": 0, "max_tokens": 120},
    )
    result = await agent.run(
        message_body,
        usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0),
    )
    return result.output


async def generate_sms_reply_with_llm(
    *,
    inbound_body: str,
    run: Run | None,
    settings: Settings,
) -> str:
    """Generate one concise SMS reply grounded in the completed run context."""
    from app.services.model_factory import create_model
    from app.workflows.config_models import WorkflowProvider

    provider = WorkflowProvider(settings.sms_reply_provider)
    model = create_model(provider, settings.sms_reply_model, settings)
    agent = Agent(
        model=model,
        instructions=(
            "Reply as the bounded messy-notes demo over SMS. Keep the response "
            "under 320 characters, helpful, and grounded only in the run context. "
            "Do not imply web lookup, OCR, images, audio/video, or an open-ended "
            "chat. If unsure, ask them to return to the app."
        ),
        output_type=SmsReply,
        model_settings={"temperature": 0.3, "max_tokens": 120},
    )
    context = (
        f"Run title: {run.title or 'Untitled run'}\n"
        f"Run status: {run.status}\n"
        f"Generated brief JSON: {run.output_brief_serialized or '{}'}\n"
        if run is not None
        else "No linked run context.\n"
    )
    result = await agent.run(
        f"{context}\nInbound SMS: {inbound_body}",
        usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0),
    )
    return result.output.body.strip()[:320]
