"""Automatic invite request fulfillment."""

from __future__ import annotations

from datetime import UTC, datetime
import asyncio
import html
import logging
from secrets import token_urlsafe
from typing import Any, Callable, cast

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.experiences import EXPERIENCE_LABELS, ExperienceId, parse_experience_id
from app.core.logging import log_event
from app.db.models import InvitationCode, InvitationRequest
from app.db.session import get_session_factory
from app.services.email import (
    EmailDraft,
    EmailSender,
    get_invite_email_sender,
)

logger = logging.getLogger(__name__)

INVITE_REQUEST_MAX_USES = 10


class InviteEmailContent(BaseModel):
    """Structured output for generated invite email copy."""

    subject: str = Field(min_length=1, max_length=120)
    text_body: str = Field(min_length=1, max_length=3000)
    html_body: str = Field(min_length=1, max_length=4000)


EmailDrafter = Callable[[InvitationRequest, InvitationCode, Settings], EmailDraft]


def fulfill_invite_request(
    invite_request_id: int,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    email_sender: EmailSender | None = None,
    email_drafter: EmailDrafter | None = None,
) -> None:
    """Create an invite code, draft a personalized email, and send it."""
    active_settings = settings or get_settings()
    active_session_factory = session_factory or get_session_factory()
    active_email_sender = email_sender or get_invite_email_sender(active_settings)
    active_email_drafter = email_drafter or build_invite_email_draft

    with active_session_factory() as db:
        invite_request = db.get(InvitationRequest, invite_request_id)
        if invite_request is None:
            log_event(
                logger,
                "invite_request_fulfillment_missing_request",
                level=logging.ERROR,
                invitation_request_id=invite_request_id,
            )
            return

        if invite_request.invitation_codes:
            return

        invite_request.fulfillment_status = "processing"
        invite_request.fulfillment_error = cast(Any, None)
        db.commit()

        try:
            invitation_code = InvitationCode(
                code=_generate_unique_code(db),
                label=_request_experience_id(invite_request).value,
                max_uses=INVITE_REQUEST_MAX_USES,
                is_active=True,
                use_count=0,
                invitation_request_id=invite_request.id,
            )
            db.add(invitation_code)
            db.commit()
            db.refresh(invite_request)
            db.refresh(invitation_code)

            draft = active_email_drafter(
                invite_request, invitation_code, active_settings
            )
            active_email_sender.send_invite_email(draft)

            now = datetime.now(UTC)
            invite_request.status = "fulfilled"
            invite_request.fulfillment_status = "sent"
            invite_request.fulfilled_at = now
            invite_request.email_sent_at = now
            invite_request.fulfillment_error = cast(Any, None)
            db.add(invite_request)
            db.commit()
            log_event(
                logger,
                "invite_request_fulfilled",
                invitation_request_id=invite_request.id,
                invitation_code_id=invitation_code.id,
            )
        except Exception as exc:
            db.rollback()
            failed_request = db.get(InvitationRequest, invite_request_id)
            if failed_request is not None:
                failed_request.status = "email_failed"
                failed_request.fulfillment_status = "failed"
                failed_request.fulfillment_error = str(exc)
                db.add(failed_request)
                db.commit()
            log_event(
                logger,
                "invite_request_fulfillment_failed",
                level=logging.ERROR,
                invitation_request_id=invite_request_id,
                error=str(exc),
            )


def build_invite_email_draft(
    invite_request: InvitationRequest,
    invitation_code: InvitationCode,
    settings: Settings,
) -> EmailDraft:
    """Build personalized invite email content with a deterministic fallback."""
    try:
        content = asyncio.run(
            _draft_personalized_email(invite_request, invitation_code, settings)
        )
        return EmailDraft(
            provider=f"pydantic-ai:{settings.invite_email_draft_provider}",
            to_email=invite_request.email,
            subject=content.subject,
            text_body=content.text_body,
            html_body=content.html_body,
            send_ready=True,
        )
    except Exception:
        log_event(
            logger,
            "invite_email_draft_fallback_used",
            level=logging.WARNING,
            invitation_request_id=invite_request.id,
        )
        return build_fallback_invite_email(invite_request, invitation_code, settings)


async def _draft_personalized_email(
    invite_request: InvitationRequest,
    invitation_code: InvitationCode,
    settings: Settings,
) -> InviteEmailContent:
    from app.services.model_factory import create_model, create_provider_model_settings
    from app.workflows.config_models import WorkflowProvider

    provider = WorkflowProvider(settings.invite_email_draft_provider)
    model = create_model(provider, settings.invite_email_draft_model, settings)
    agent = Agent(
        model=model,
        instructions=(
            "Draft short, warm, professional invitation emails for an invite-only "
            "selected demo experience. Personalize wording only from the request context. "
            "Do not approve, reject, or evaluate the requester. Include the exact "
            "invite code and simple start instructions. Keep the email concise."
        ),
        output_type=InviteEmailContent,
        model_settings=create_provider_model_settings(
            provider=provider,
            timeout=None,
            temperature=None,
            max_tokens=700,
        ),
    )
    base_url = settings.invite_email_base_url.rstrip("/")
    experience_id = _request_experience_id(invite_request)
    experience_label = EXPERIENCE_LABELS[experience_id]
    result = await agent.run(
        (
            f"Requester name: {invite_request.name}\n"
            f"Requester email: {invite_request.email}\n"
            f"Requested experience: {experience_label}\n"
            f"Reason for access: {invite_request.reason}\n"
            f"Invitation code: {invitation_code.code}\n"
            f"Start URL: {base_url}/\n"
            "Mention that the demo supports pasted text, text files, and PDFs "
            "with extractable text."
        ),
        usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0),
    )
    return result.output


def build_fallback_invite_email(
    invite_request: InvitationRequest,
    invitation_code: InvitationCode,
    settings: Settings,
) -> EmailDraft:
    """Build deterministic invite email content when LLM drafting is unavailable."""
    base_url = settings.invite_email_base_url.rstrip("/")
    experience_id = _request_experience_id(invite_request)
    experience_label = EXPERIENCE_LABELS[experience_id]
    safe_name = html.escape(invite_request.name)
    safe_code = html.escape(invitation_code.code)
    safe_base_url = html.escape(base_url)
    safe_experience_label = html.escape(experience_label)
    subject = f"Your {experience_label} invitation"
    text_body = (
        f"Hi {invite_request.name},\n\n"
        f"Thanks for requesting access to {experience_label}. "
        "Based on your note, this should give you a practical look at the "
        "bounded workflow.\n\n"
        f"Invitation code: {invitation_code.code}\n"
        f"Start here: {base_url}/\n\n"
        "The demo supports pasted text, text files, and PDFs with extractable "
        "text. It does not support OCR, images, audio, video, or web lookup.\n"
    )
    html_body = (
        f"<p>Hi {safe_name},</p>"
        f"<p>Thanks for requesting access to {safe_experience_label}. Based on "
        "your note, this should give you a practical look at the bounded workflow.</p>"
        f"<p><strong>Invitation code:</strong> {safe_code}</p>"
        f'<p>Start here: <a href="{safe_base_url}/">{safe_base_url}/</a></p>'
        "<p>The demo supports pasted text, text files, and PDFs with extractable "
        "text. It does not support OCR, images, audio, video, or web lookup.</p>"
    )
    return EmailDraft(
        provider="fallback-template",
        to_email=invite_request.email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        send_ready=True,
    )


def _generate_unique_code(db: Session) -> str:
    for _ in range(20):
        code = f"demo-{token_urlsafe(8)}"
        existing = db.query(InvitationCode).filter(InvitationCode.code == code).first()
        if existing is None:
            return code
    raise RuntimeError("Could not generate a unique invitation code.")


def _request_experience_id(invite_request: InvitationRequest) -> ExperienceId:
    """Return the selected experience for an invite request."""
    if invite_request.label is None:
        return ExperienceId.MESSY_NOTES
    return parse_experience_id(invite_request.label)
