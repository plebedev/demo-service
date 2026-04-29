"""Tests for invitation redemption and signed access-token enforcement."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.security import create_access_token, verify_access_token
from app.db.models import InvitationCode, InvitationRedemption, InvitationRequest


@dataclass(frozen=True)
class TokenTestSettings:
    """Small settings stub for token helper unit tests."""

    access_token_signing_key: str = "test-signing-key"
    access_token_ttl_seconds: int = 3600


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
    assert payload["message"] == "Invite request received for manual review."

    stored = db_session.get(InvitationRequest, payload["id"])
    assert stored is not None
    assert stored.name == "Ada Lovelace"
    assert stored.email == "ada@example.com"
    assert stored.reason == "I want to evaluate the bounded messy-notes workflow."
    assert stored.user_agent == "pytest"
    assert stored.ip_hash is not None


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


def test_admin_invite_request_review_and_details(client) -> None:
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


def test_issue_invite_code_draft_links_request_and_code(client, db_session) -> None:
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
