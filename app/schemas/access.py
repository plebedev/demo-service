"""Schemas for invite redemption and access token verification."""

from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator

from app.core.experiences import ExperienceId
from app.core.phase1 import Phase1Guardrails


class RedeemInvitationRequest(BaseModel):
    """Request body for redeeming an invitation code."""

    code: str = Field(min_length=1, max_length=128)


class InviteRequestCreate(BaseModel):
    """Public request body for invite-request intake."""

    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    experience_id: ExperienceId
    reason: str = Field(min_length=10, max_length=2000)

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

    id: int
    status: str
    message: str


class AccessTokenResponse(BaseModel):
    """Response returned after a successful invitation redemption."""

    access_token: str
    token_type: str = "bearer"
    experience_id: ExperienceId
    redirect_path: str
    expires_at: datetime
    phase1: Phase1Guardrails


class AccessTokenVerificationResponse(BaseModel):
    """Response returned when a stored access token is still valid."""

    status: str
    token_id: str
    experience_id: ExperienceId
    redirect_path: str
    expires_at: datetime
    phase1: Phase1Guardrails
