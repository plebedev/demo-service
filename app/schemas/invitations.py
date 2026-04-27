"""Schemas for internal invitation management endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class CreateInvitationCodeRequest(BaseModel):
    """Payload for creating an invitation code."""

    code: str | None = Field(default=None, min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=255)
    max_uses: int | None = Field(default=None, ge=1)


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


class InvitationStatsResponse(BaseModel):
    """Aggregated invitation-code usage statistics."""

    total_codes: int
    active_codes: int
    total_redemptions: int
    codes: list[InvitationCodeResponse]
