"""Schemas for invite redemption and access token verification."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.phase1 import Phase1Guardrails


class RedeemInvitationRequest(BaseModel):
    """Request body for redeeming an invitation code."""

    code: str = Field(min_length=1, max_length=128)


class AccessTokenResponse(BaseModel):
    """Response returned after a successful invitation redemption."""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    phase1: Phase1Guardrails


class AccessTokenVerificationResponse(BaseModel):
    """Response returned when a stored access token is still valid."""

    status: str
    token_id: str
    expires_at: datetime
    phase1: Phase1Guardrails
