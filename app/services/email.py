"""Email drafting and delivery helpers for invite operations."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
import smtplib
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


@dataclass(frozen=True)
class EmailSendResult:
    """Result metadata from an outbound email send."""

    provider: str
    to_email: str
    bcc_email: str


class EmailSender(Protocol):
    """Provider boundary for delivering email."""

    name: str

    def send_invite_email(self, draft: EmailDraft) -> EmailSendResult:
        """Send a prepared invite email."""


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
        """Build a deterministic invite email draft."""
        base_url = self._settings.invite_email_base_url.rstrip("/")
        subject = "Your messy-notes demo invitation"
        text_body = (
            f"Hi {invite_request.name},\n\n"
            "Thanks for requesting access to the messy-notes demo. "
            f"Use this invitation code to enter the demo: {invitation_code.code}\n\n"
            f"Start here: {base_url}/\n\n"
            "This is an invite-only phase-1 demo. It supports pasted text, text "
            "files, and PDFs with extractable text. It does not support OCR, "
            "images, audio, video, or web lookup.\n"
        )
        html_body = (
            f"<p>Hi {invite_request.name},</p>"
            "<p>Thanks for requesting access to the messy-notes demo.</p>"
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
    """OCI Email Delivery draft provider."""

    name = "oci-email-delivery"


class OciSmtpEmailSender:
    """Send invite email through OCI Email Delivery SMTP."""

    name = "oci-email-delivery-smtp"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send_invite_email(self, draft: EmailDraft) -> EmailSendResult:
        """Send a prepared invite email through OCI's SMTP endpoint."""
        host = self._settings.oci_email_smtp_host
        username = self._settings.oci_email_smtp_username
        password = self._settings.oci_email_smtp_password
        from_address = self._settings.oci_email_from_address
        bcc_address = self._settings.invite_email_bcc_address
        missing = [
            name
            for name, value in (
                ("OCI_EMAIL_SMTP_HOST", host),
                ("OCI_EMAIL_SMTP_USERNAME", username),
                ("OCI_EMAIL_SMTP_PASSWORD", password),
                ("OCI_EMAIL_FROM_ADDRESS", from_address),
                ("INVITE_EMAIL_BCC_ADDRESS", bcc_address),
            )
            if not value
        ]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"Missing invite email configuration: {missing_text}.")

        message = EmailMessage()
        sender_name = self._settings.oci_email_from_name or "Demo invitations"
        message["From"] = formataddr((sender_name, from_address or ""))
        message["To"] = draft.to_email
        message["Bcc"] = bcc_address
        message["Subject"] = draft.subject
        message.set_content(draft.text_body)
        message.add_alternative(draft.html_body, subtype="html")

        with smtplib.SMTP(host or "", self._settings.oci_email_smtp_port) as smtp:
            smtp.starttls()
            smtp.login(username or "", password or "")
            smtp.send_message(message, from_addr=from_address)

        return EmailSendResult(
            provider=self.name,
            to_email=draft.to_email,
            bcc_email=bcc_address or "",
        )


def get_email_provider(settings: Settings) -> EmailProvider:
    """Return the configured provider boundary without sending mail."""
    if settings.email_provider == "oci":
        return OciEmailDeliveryProvider(settings)
    return StubEmailProvider(settings)


def get_invite_email_sender(settings: Settings) -> EmailSender:
    """Return the real invite email sender."""
    return OciSmtpEmailSender(settings)
