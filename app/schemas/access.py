"""Schemas for invite redemption and access token verification."""

from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator

from app.core.experiences import ExperienceId
from app.core.phase1 import Phase1Guardrails


class RedeemInvitationRequest(BaseModel):
    """Request body for redeeming an invitation code."""

    code: str = Field(
        min_length=1,
        max_length=128,
        description="Invitation code string to redeem",
    )


class InviteRequestCreate(BaseModel):
    """Public request body for invite-request intake."""

    name: str = Field(min_length=1, max_length=255, description="Applicant's full name")
    email: str = Field(
        min_length=3, max_length=320, description="Applicant's email address"
    )
    experience_id: ExperienceId = Field(
        description="Demo experience the applicant is requesting access to"
    )
    reason: str = Field(
        min_length=10,
        max_length=2000,
        description="Applicant's stated reason for requesting access",
    )

    @field_validator("name", "email", "reason")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        """Trim user-submitted invite request fields."""
        return value.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Validate a basic email shape without adding a new dependency."""
        normalized = value.lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class InviteRequestResponse(BaseModel):
    """Clean response returned after invite request submission."""

    id: int = Field(description="Database ID of the created invite request")
    status: str = Field(description="Initial review status of the request")
    message: str = Field(description="Human-readable confirmation message")


class AccessTokenResponse(BaseModel):
    """Response returned after a successful invitation redemption."""

    access_token: str = Field(description="Signed JWT access token")
    token_type: str = Field(
        default="bearer", description="Token scheme; always 'bearer'"
    )
    experience_id: ExperienceId = Field(
        description="Experience the redeemed code grants access to"
    )
    redirect_path: str = Field(
        description="Frontend route to navigate to after redemption"
    )
    expires_at: datetime = Field(description="Timestamp when the token expires")
    phase1: Phase1Guardrails = Field(
        description="Phase-1 feature flags and limits applicable to this session"
    )


class AccessTokenVerificationResponse(BaseModel):
    """Response returned when a stored access token is still valid."""

    status: str = Field(description="Verification outcome; always 'valid' on success")
    token_id: str = Field(description="Unique identifier embedded in the token")
    experience_id: ExperienceId = Field(
        description="Experience this token grants access to"
    )
    redirect_path: str = Field(
        description="Frontend route associated with this experience"
    )
    expires_at: datetime = Field(description="Timestamp when the token expires")
    phase1: Phase1Guardrails = Field(
        description="Phase-1 feature flags and limits for this session"
    )
