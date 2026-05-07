"""Schemas for internal invitation management endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.experiences import ExperienceId


class CreateInvitationCodeRequest(BaseModel):
    """Payload for creating an invitation code."""

    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Custom code string; generated automatically when omitted",
    )
    label: ExperienceId = Field(
        default=ExperienceId.MESSY_NOTES,
        description="Experience this code grants access to",
    )
    max_uses: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of redemptions; unlimited when omitted",
    )
    invitation_request_id: int | None = Field(
        default=None,
        ge=1,
        description="ID of the invite request this code fulfills",
    )


class InvitationCodeResponse(BaseModel):
    """Serialized invitation code metadata."""

    id: int = Field(description="Database ID of the invitation code")
    code: str = Field(description="Redeemable code string")
    label: ExperienceId | None = Field(
        description="Experience this code grants access to"
    )
    is_active: bool = Field(description="False when the code has been deactivated")
    max_uses: int | None = Field(
        description="Maximum allowed redemptions; null means unlimited"
    )
    use_count: int = Field(description="Number of times this code has been redeemed")
    created_at: datetime = Field(description="Timestamp when the code was created")
    last_used_at: datetime | None = Field(
        description="Timestamp of the most recent redemption"
    )
    invitation_request_id: int | None = Field(
        description="ID of the invite request this code was issued to fulfill"
    )


class InvitationRequestReviewRequest(BaseModel):
    """Payload for marking an invite request reviewed."""

    status: str = Field(
        default="reviewed",
        pattern="^(reviewed|approved|rejected)$",
        description="Review outcome: 'reviewed', 'approved', or 'rejected'",
    )
    reviewer_note: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional operator note recorded with the review decision",
    )


class InvitationRequestResponse(BaseModel):
    """Serialized invite request for internal operator review."""

    id: int = Field(description="Database ID of the invite request")
    name: str = Field(description="Applicant's name")
    email: str = Field(description="Applicant's email address")
    label: ExperienceId | None = Field(
        description="Experience the applicant requested access to"
    )
    reason: str = Field(description="Applicant's stated reason for requesting access")
    status: str = Field(
        description="Review status: 'submitted', 'reviewed', 'approved', or 'rejected'"
    )
    created_at: datetime = Field(description="Timestamp when the request was submitted")
    reviewed_at: datetime | None = Field(
        description="Timestamp when an operator reviewed the request"
    )
    reviewer_note: str | None = Field(
        description="Operator note recorded at review time"
    )
    fulfillment_status: str = Field(
        description="Fulfillment pipeline status: 'pending', 'fulfilled', or 'failed'"
    )
    fulfilled_at: datetime | None = Field(
        description="Timestamp when an invite code was issued to the applicant"
    )
    email_sent_at: datetime | None = Field(
        description="Timestamp when the invite email was delivered"
    )
    fulfillment_error: str | None = Field(
        description="Error detail if the fulfillment pipeline failed"
    )
    issued_invitation_code_id: int | None = Field(
        description="Database ID of the code issued to this request"
    )
    issued_invitation_code: str | None = Field(
        description="Code string issued to this request"
    )


class InviteEmailDraftResponse(BaseModel):
    """Draft invite email payload generated for operator review."""

    provider: str = Field(description="Email provider used to send the message")
    to_email: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    text_body: str = Field(description="Plain-text version of the email body")
    html_body: str = Field(description="HTML version of the email body")
    invitation_code_id: int = Field(description="ID of the code embedded in the email")
    invitation_request_id: int = Field(
        description="ID of the invite request this email fulfills"
    )
    send_ready: bool = Field(
        description="True when all required fields are populated and the email can be sent"
    )


class IssueInviteCodeDraftRequest(BaseModel):
    """Request for linking an invite request to a new code and draft email."""

    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Custom code string; generated automatically when omitted",
    )
    label: ExperienceId | None = Field(
        default=None,
        description="Experience to grant; falls back to the request's experience when omitted",
    )
    max_uses: int | None = Field(
        default=1,
        ge=1,
        description="Maximum redemptions for the new code",
    )
    reviewer_note: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional operator note recorded with the review",
    )


class IssueInviteCodeDraftResponse(BaseModel):
    """Created code plus draft email payload for a reviewed request."""

    request: InvitationRequestResponse = Field(
        description="Updated invite request after code issuance"
    )
    invitation_code: InvitationCodeResponse = Field(
        description="Newly created invitation code"
    )
    email_draft: InviteEmailDraftResponse = Field(
        description="Draft email ready for operator review before sending"
    )


class InvitationStatsResponse(BaseModel):
    """Aggregated invitation-code usage statistics."""

    total_codes: int = Field(description="Total number of codes ever created")
    active_codes: int = Field(description="Number of codes that are currently active")
    total_redemptions: int = Field(
        description="Total number of successful redemptions across all codes"
    )
    codes: list[InvitationCodeResponse] = Field(
        description="All invitation codes with their current metadata"
    )
