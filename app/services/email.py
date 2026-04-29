"""Minimal email delivery scaffolding for invite operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.models.invitation import InvitationCode, InvitationRequest


@dataclass(frozen=True)
class EmailDraft:
    """A send-ready payload that is not automatically delivered."""

    provider: str
    to_email: str
    subject: str
    text_body: str
    html_body: str
    send_ready: bool


class EmailProvider(Protocol):
    """Provider boundary for future email delivery."""

    name: str

    def build_invite_email(
        self,
        invite_request: InvitationRequest,
        invitation_code: InvitationCode,
    ) -> EmailDraft:
        """Return a draft invite email payload."""


class StubEmailProvider:
    """Draft-only provider used until real delivery is explicitly enabled."""

    name = "stub"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def build_invite_email(
        self,
        invite_request: InvitationRequest,
        invitation_code: InvitationCode,
    ) -> EmailDraft:
        """Build the operator-reviewed invite email draft."""
        base_url = self._settings.invite_email_base_url.rstrip("/")
        subject = "Your messy-notes demo invitation"
        text_body = (
            f"Hi {invite_request.name},\n\n"
            "Your request for the messy-notes demo has been reviewed. "
            f"Use this invitation code to enter the demo: {invitation_code.code}\n\n"
            f"Start here: {base_url}/\n\n"
            "This is an invite-only phase-1 demo. It supports pasted text, text "
            "files, and PDFs with extractable text. It does not support OCR, "
            "images, audio, video, or web lookup.\n"
        )
        html_body = (
            f"<p>Hi {invite_request.name},</p>"
            "<p>Your request for the messy-notes demo has been reviewed.</p>"
            f"<p><strong>Invitation code:</strong> {invitation_code.code}</p>"
            f'<p>Start here: <a href="{base_url}/">{base_url}/</a></p>'
            "<p>This phase-1 demo supports pasted text, text files, and PDFs "
            "with extractable text. It does not support OCR, images, audio, "
            "video, or web lookup.</p>"
        )
        return EmailDraft(
            provider=self.name,
            to_email=invite_request.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            send_ready=False,
        )


class OciEmailDeliveryProvider(StubEmailProvider):
    """OCI Email Delivery placeholder; delivery is intentionally not wired yet."""

    name = "oci-email-delivery-draft"


def get_email_provider(settings: Settings) -> EmailProvider:
    """Return the configured provider boundary without sending mail."""
    if settings.email_provider == "oci":
        return OciEmailDeliveryProvider(settings)
    return StubEmailProvider(settings)
