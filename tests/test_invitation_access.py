"""Tests for invitation redemption and signed access-token enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.security import create_access_token, verify_access_token
from app.db.models import InvitationCode, InvitationRedemption, InvitationRequest
from app.services.email import EmailDraft, EmailSendResult
from app.services.email import OciSmtpEmailSender
from app.services.invite_fulfillment import (
    INVITE_REQUEST_MAX_USES,
    InviteEmailContent,
    build_fallback_invite_email,
    build_invite_email_draft,
    fulfill_invite_request,
)


@dataclass(frozen=True)
class TokenTestSettings:
    """Small settings stub for token helper unit tests."""

    access_token_signing_key: str = "test-signing-key"
    access_token_ttl_seconds: int = 3600


class RecordingEmailSender:
    """Test email sender that records the sent draft."""

    name = "recording"

    def __init__(self) -> None:
        self.sent: list[EmailDraft] = []

    def send_invite_email(self, draft: EmailDraft) -> EmailSendResult:
        self.sent.append(draft)
        return EmailSendResult(
            provider=self.name,
            to_email=draft.to_email,
            bcc_email="operator@example.com",
        )


class FailingEmailSender:
    """Test email sender that simulates an SMTP failure."""

    name = "failing"

    def send_invite_email(self, draft: EmailDraft) -> EmailSendResult:
        del draft
        raise RuntimeError("SMTP send failed")


def create_code(
    client, code: str, *, max_uses: int | None = None, is_active: bool = True
):
    """Insert an invitation code through the admin API for test setup."""
    response = client.post(
        "/api/internal/admin/invitations",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"code": code, "max_uses": max_uses},
    )
    assert response.status_code == 201
    if not is_active:
        created_id = response.json()["id"]
        deactivate = client.post(
            f"/api/internal/admin/invitations/{created_id}/deactivate",
            headers={"X-Admin-Secret": "test-admin-secret"},
        )
        assert deactivate.status_code == 200
    return response.json()


def test_invalid_invitation_code_is_rejected(client) -> None:
    response = client.post("/api/access/redeem", json={"code": "missing-code"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Invitation code not found."


def test_inactive_invitation_code_is_rejected(client) -> None:
    create_code(client, "inactive-demo", is_active=False)

    response = client.post("/api/access/redeem", json={"code": "inactive-demo"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Invitation code is inactive."


def test_max_use_invitation_code_is_rejected(client) -> None:
    create_code(client, "single-use", max_uses=1)

    first = client.post("/api/access/redeem", json={"code": "single-use"})
    assert first.status_code == 200

    second = client.post("/api/access/redeem", json={"code": "single-use"})
    assert second.status_code == 403
    assert second.json()["detail"] == "Invitation code has reached its usage limit."


def test_signed_token_issuance_and_verification(client) -> None:
    settings = TokenTestSettings()
    create_code(client, "demo-access")

    redeem = client.post("/api/access/redeem", json={"code": "demo-access"})
    assert redeem.status_code == 200
    payload = redeem.json()
    token = payload["access_token"]

    verify = client.get(
        "/api/access/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert verify.status_code == 200
    verified_payload = verify.json()
    assert verified_payload["status"] == "ok"
    assert verified_payload["token_id"]
    assert verified_payload["phase1"]["demo_only"] is True

    claims = verify_access_token(token, settings)
    assert claims.code == "demo-access"


def test_protected_status_endpoint_requires_valid_token(client) -> None:
    unauthenticated = client.get("/api/status")
    assert unauthenticated.status_code == 401

    create_code(client, "status-access")
    redeem = client.post("/api/access/redeem", json={"code": "status-access"})
    token = redeem.json()["access_token"]

    authenticated = client.get(
        "/api/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert authenticated.status_code == 200
    assert authenticated.json()["phase1"]["limits"]["max_files_per_run"] == 3


def test_redeeming_code_increments_usage_and_creates_redemption(
    client, db_session
) -> None:
    created = create_code(client, "tracked-code")

    redeem = client.post(
        "/api/access/redeem",
        json={"code": "tracked-code"},
        headers={"User-Agent": "pytest-agent"},
    )
    assert redeem.status_code == 200

    invitation_code = db_session.get(InvitationCode, created["id"])
    redemption = (
        db_session.query(InvitationRedemption)
        .filter(InvitationRedemption.invitation_code_id == created["id"])
        .one()
    )
    assert invitation_code is not None
    assert invitation_code.use_count == 1
    assert invitation_code.last_used_at is not None
    assert redemption.user_agent == "pytest-agent"
    assert redemption.ip_hash is not None


def test_invite_request_submission_persists_for_manual_review(
    client, db_session
) -> None:
    response = client.post(
        "/api/access/invite-requests",
        json={
            "name": "Ada Lovelace",
            "email": "ADA@Example.COM",
            "reason": "I want to evaluate the bounded messy-notes workflow.",
        },
        headers={"User-Agent": "pytest"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "submitted"
    assert payload["message"] == (
        "Invite request received. Your invite is being prepared and emailed."
    )

    stored = db_session.get(InvitationRequest, payload["id"])
    assert stored is not None
    assert stored.name == "Ada Lovelace"
    assert stored.email == "ada@example.com"
    assert stored.reason == "I want to evaluate the bounded messy-notes workflow."
    assert stored.user_agent == "pytest"
    assert stored.ip_hash is not None


def test_invite_request_submission_triggers_background_fulfillment(
    client, monkeypatch
) -> None:
    triggered: list[int] = []

    def fake_fulfill(invite_request_id: int) -> None:
        triggered.append(invite_request_id)

    monkeypatch.setattr("app.api.routes.access.fulfill_invite_request", fake_fulfill)

    response = client.post(
        "/api/access/invite-requests",
        json={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "reason": "I want to evaluate the bounded messy-notes workflow.",
        },
    )

    assert response.status_code == 201
    assert triggered == [response.json()["id"]]


def test_fulfillment_creates_linked_code_and_sends_email(
    db_session, session_factory
) -> None:
    invite_request = InvitationRequest(
        name="Ada Lovelace",
        email="ada@example.com",
        reason="I want to evaluate the bounded messy-notes workflow.",
    )
    db_session.add(invite_request)
    db_session.commit()
    db_session.refresh(invite_request)
    sender = RecordingEmailSender()

    def draft(
        request: InvitationRequest, code: InvitationCode, settings: Any
    ) -> EmailDraft:
        del settings
        return EmailDraft(
            provider="test-drafter",
            to_email=request.email,
            subject="Your invite",
            text_body=f"Code: {code.code}",
            html_body=f"<p>Code: {code.code}</p>",
            send_ready=True,
        )

    fulfill_invite_request(
        invite_request.id,
        session_factory=session_factory,
        email_sender=sender,
        email_drafter=draft,
    )

    db_session.expire_all()
    stored = db_session.get(InvitationRequest, invite_request.id)
    assert stored is not None
    assert stored.status == "fulfilled"
    assert stored.fulfillment_status == "sent"
    assert stored.email_sent_at is not None
    assert len(stored.invitation_codes) == 1
    assert stored.invitation_codes[0].max_uses == INVITE_REQUEST_MAX_USES
    assert stored.invitation_codes[0].code.startswith("demo-")
    assert sender.sent[0].to_email == "ada@example.com"
    assert stored.invitation_codes[0].code in sender.sent[0].text_body


def test_fulfillment_records_email_send_failure(
    db_session, session_factory
) -> None:
    invite_request = InvitationRequest(
        name="Grace Hopper",
        email="grace@example.com",
        reason="I want to review the demo workflow for operators.",
    )
    db_session.add(invite_request)
    db_session.commit()
    db_session.refresh(invite_request)

    def draft(
        request: InvitationRequest, code: InvitationCode, settings: Any
    ) -> EmailDraft:
        del settings
        return EmailDraft(
            provider="test-drafter",
            to_email=request.email,
            subject="Your invite",
            text_body=f"Code: {code.code}",
            html_body=f"<p>Code: {code.code}</p>",
            send_ready=True,
        )

    fulfill_invite_request(
        invite_request.id,
        session_factory=session_factory,
        email_sender=FailingEmailSender(),
        email_drafter=draft,
    )

    db_session.expire_all()
    stored = db_session.get(InvitationRequest, invite_request.id)
    assert stored is not None
    assert stored.status == "email_failed"
    assert stored.fulfillment_status == "failed"
    assert stored.fulfillment_error == "SMTP send failed"
    assert len(stored.invitation_codes) == 1
    assert stored.invitation_codes[0].max_uses == INVITE_REQUEST_MAX_USES


def test_personalized_email_draft_path_uses_llm_output(
    monkeypatch,
) -> None:
    invite_request = InvitationRequest(
        id=1,
        name="Katherine Johnson",
        email="katherine@example.com",
        reason="I need a practical workflow demo for note cleanup.",
    )
    invitation_code = InvitationCode(id=2, code="demo-personal", max_uses=10)

    async def fake_draft(
        request: InvitationRequest, code: InvitationCode, settings: Any
    ) -> InviteEmailContent:
        del request, code, settings
        return InviteEmailContent(
            subject="A personal invite",
            text_body="Here is demo-personal for your note cleanup workflow.",
            html_body="<p>Here is demo-personal.</p>",
        )

    monkeypatch.setattr(
        "app.services.invite_fulfillment._draft_personalized_email", fake_draft
    )

    draft = build_invite_email_draft(invite_request, invitation_code, get_settings())

    assert draft.provider == "pydantic-ai:openai"
    assert draft.subject == "A personal invite"
    assert "demo-personal" in draft.text_body


def test_email_draft_falls_back_when_llm_drafting_fails(
    monkeypatch,
) -> None:
    invite_request = InvitationRequest(
        id=1,
        name="Katherine Johnson",
        email="katherine@example.com",
        reason="I need a practical workflow demo for note cleanup.",
    )
    invitation_code = InvitationCode(id=2, code="demo-fallback", max_uses=10)

    async def fail_draft(
        request: InvitationRequest, code: InvitationCode, settings: Any
    ) -> InviteEmailContent:
        del request, code, settings
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "app.services.invite_fulfillment._draft_personalized_email", fail_draft
    )

    draft = build_invite_email_draft(invite_request, invitation_code, get_settings())

    assert draft.provider == "fallback-template"
    assert draft.to_email == "katherine@example.com"
    assert "demo-fallback" in draft.text_body


def test_fallback_email_includes_invite_code_and_instructions() -> None:
    invite_request = InvitationRequest(
        id=1,
        name="Ada Lovelace",
        email="ada@example.com",
        reason="I want to evaluate the bounded messy-notes workflow.",
    )
    invitation_code = InvitationCode(id=2, code="demo-fallback", max_uses=10)

    draft = build_fallback_invite_email(
        invite_request, invitation_code, get_settings()
    )

    assert draft.to_email == "ada@example.com"
    assert "demo-fallback" in draft.text_body
    assert "Start here:" in draft.text_body


def test_oci_email_sender_uses_configured_bcc(monkeypatch) -> None:
    sent: dict[str, Any] = {}

    class FakeSmtp:
        def __init__(self, host: str, port: int) -> None:
            sent["host"] = host
            sent["port"] = port

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def starttls(self) -> None:
            sent["tls"] = True

        def login(self, username: str, password: str) -> None:
            sent["username"] = username
            sent["password"] = password

        def send_message(
            self, message: Any, from_addr: str, to_addrs: list[str] | None = None
        ) -> None:
            sent["message"] = message
            sent["from_addr"] = from_addr
            sent["to_addrs"] = to_addrs

    monkeypatch.setattr("app.services.email.smtplib.SMTP", FakeSmtp)
    settings = get_settings().model_copy(
        update={
            "oci_email_smtp_host": "smtp.email.us-ashburn-1.oci.oraclecloud.com",
            "oci_email_smtp_port": 587,
            "oci_email_smtp_username": "smtp-user",
            "oci_email_smtp_password": "smtp-password",
            "oci_email_from_address": "demo@example.com",
            "oci_email_from_name": "Demo Team",
            "invite_email_bcc_address": "operator@example.com",
        }
    )
    draft = EmailDraft(
        provider="test",
        to_email="ada@example.com",
        subject="Your invite",
        text_body="Plain invite",
        html_body="<p>Plain invite</p>",
        send_ready=True,
    )

    result = OciSmtpEmailSender(settings).send_invite_email(draft)

    assert result.bcc_email == "operator@example.com"
    assert sent["to_addrs"] is None
    assert sent["message"]["To"] == "ada@example.com"
    assert sent["message"]["Bcc"] == "operator@example.com"
    assert sent["message"]["From"] == "Demo Team <demo@example.com>"


def test_invite_request_validates_basic_input(client) -> None:
    response = client.post(
        "/api/access/invite-requests",
        json={
            "name": "",
            "email": "not-an-email",
            "reason": "too short",
        },
    )

    assert response.status_code == 422


def test_admin_stats_and_list_endpoints(client) -> None:
    create_code(client, "stats-a")
    create_code(client, "stats-b", max_uses=2)

    listing = client.get(
        "/api/internal/admin/invitations",
        headers={"X-Admin-Secret": "test-admin-secret"},
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 2

    stats = client.get(
        "/api/internal/admin/invitations/stats",
        headers={"X-Admin-Secret": "test-admin-secret"},
    )
    assert stats.status_code == 200
    payload = stats.json()
    assert payload["total_codes"] == 2
    assert payload["active_codes"] == 2
    assert payload["total_redemptions"] == 0


def test_admin_invite_request_review_and_details(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.access.fulfill_invite_request",
        lambda invite_request_id: None,
    )
    submitted = client.post(
        "/api/access/invite-requests",
        json={
            "name": "Grace Hopper",
            "email": "grace@example.com",
            "reason": "I want to review the demo workflow for operators.",
        },
    )
    request_id = submitted.json()["id"]

    listing = client.get(
        "/api/internal/admin/invitations/requests",
        headers={"X-Admin-Secret": "test-admin-secret"},
    )
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == request_id
    assert listing.json()[0]["issued_invitation_code_id"] is None

    reviewed = client.post(
        f"/api/internal/admin/invitations/requests/{request_id}/review",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"status": "reviewed", "reviewer_note": "Looks relevant."},
    )
    assert reviewed.status_code == 200
    payload = reviewed.json()
    assert payload["status"] == "reviewed"
    assert payload["reviewed_at"] is not None
    assert payload["reviewer_note"] == "Looks relevant."

    detail = client.get(
        f"/api/internal/admin/invitations/requests/{request_id}",
        headers={"X-Admin-Secret": "test-admin-secret"},
    )
    assert detail.status_code == 200
    assert detail.json()["email"] == "grace@example.com"


def test_issue_invite_code_draft_links_request_and_code(
    client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.routes.access.fulfill_invite_request",
        lambda invite_request_id: None,
    )
    submitted = client.post(
        "/api/access/invite-requests",
        json={
            "name": "Katherine Johnson",
            "email": "katherine@example.com",
            "reason": "I need a practical workflow demo for note cleanup.",
        },
    )
    request_id = submitted.json()["id"]

    issued = client.post(
        f"/api/internal/admin/invitations/requests/{request_id}/issue-code-draft",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"code": "linked-code", "reviewer_note": "Approved for demo."},
    )
    assert issued.status_code == 201
    payload = issued.json()
    assert payload["request"]["status"] == "approved"
    assert payload["request"]["issued_invitation_code"] == "linked-code"
    assert payload["invitation_code"]["invitation_request_id"] == request_id
    assert payload["email_draft"]["to_email"] == "katherine@example.com"
    assert payload["email_draft"]["send_ready"] is False
    assert "linked-code" in payload["email_draft"]["text_body"]

    stored = db_session.get(InvitationRequest, request_id)
    assert stored is not None
    assert stored.status == "approved"
    assert stored.invitation_codes[0].code == "linked-code"

    duplicate = client.post(
        f"/api/internal/admin/invitations/requests/{request_id}/issue-code-draft",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == (
        "Invite request already has an issued invitation code."
    )


def test_admin_invite_request_paths_require_secret(client) -> None:
    response = client.get("/api/internal/admin/invitations/requests")
    assert response.status_code == 401


def test_create_access_token_returns_expected_claims() -> None:
    settings = TokenTestSettings()
    token, claims = create_access_token(
        settings=settings,
        invitation_code_id=42,
        code="direct-token",
    )
    verified = verify_access_token(token, settings)
    assert claims.token_id == verified.token_id
    assert verified.invitation_code_id == 42
