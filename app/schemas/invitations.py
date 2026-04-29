"""Schemas for internal invitation management endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class CreateInvitationCodeRequest(BaseModel):
    """Payload for creating an invitation code."""

    code: str | None = Field(default=None, min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=255)
    max_uses: int | None = Field(default=None, ge=1)
    invitation_request_id: int | None = Field(default=None, ge=1)


class InvitationCodeResponse(BaseModel):
    """Serialized invitation code metadata."""

    id: int
    code: str
    label: str | None
    is_active: bool
    max_uses: int | None
    use_count: int
    created_at: datetime
    last_used_at: datetime | None
    invitation_request_id: int | None


class InvitationRequestReviewRequest(BaseModel):
    """Payload for marking an invite request reviewed."""

    status: str = Field(default="reviewed", pattern="^(reviewed|approved|rejected)$")
    reviewer_note: str | None = Field(default=None, max_length=2000)


class InvitationRequestResponse(BaseModel):
    """Serialized invite request for internal operator review."""

    id: int
    name: str
    email: str
    reason: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None
    reviewer_note: str | None
    issued_invitation_code_id: int | None
    issued_invitation_code: str | None


class InviteEmailDraftResponse(BaseModel):
    """Draft invite email payload generated for operator review."""

    provider: str
    to_email: str
    subject: str
    text_body: str
    html_body: str
    invitation_code_id: int
    invitation_request_id: int
    send_ready: bool


class IssueInviteCodeDraftRequest(BaseModel):
    """Request for linking an invite request to a new code and draft email."""

    code: str | None = Field(default=None, min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=255)
    max_uses: int | None = Field(default=1, ge=1)
    reviewer_note: str | None = Field(default=None, max_length=2000)


class IssueInviteCodeDraftResponse(BaseModel):
    """Created code plus draft email payload for a reviewed request."""

    request: InvitationRequestResponse
    invitation_code: InvitationCodeResponse
    email_draft: InviteEmailDraftResponse


class InvitationStatsResponse(BaseModel):
    """Aggregated invitation-code usage statistics."""

    total_codes: int
    active_codes: int
    total_redemptions: int
    codes: list[InvitationCodeResponse]
