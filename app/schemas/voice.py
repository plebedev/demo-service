"""Pydantic schemas for voice experience admin and configuration APIs."""

from datetime import datetime

from pydantic import BaseModel, Field


class VoicePersonaCreateRequest(BaseModel):
    """Payload for creating a voice assistant persona."""

    name: str = Field(
        min_length=1, max_length=255, description="Display name for the persona"
    )
    instructions: str = Field(
        min_length=1,
        max_length=16000,
        description="System-level instructions passed to the xAI voice agent session",
    )
    capabilities: str | None = Field(
        default=None,
        max_length=8000,
        description=(
            "Structured description of what this persona handles. "
            "Used for greeting synthesis and future routing."
        ),
    )
    tool_config: str | None = Field(
        default=None,
        max_length=32000,
        description=(
            "Curated guidance: intake questions, scoring rules, recommendation templates. "
            "JSON or structured text embedded in the persona."
        ),
    )


class VoicePersonaUpdateRequest(BaseModel):
    """Payload for updating an existing voice persona."""

    instructions: str | None = Field(
        default=None,
        min_length=1,
        max_length=16000,
        description="Updated system-level instructions",
    )
    capabilities: str | None = Field(
        default=None,
        max_length=8000,
        description="Updated capabilities description",
    )
    tool_config: str | None = Field(
        default=None,
        max_length=32000,
        description="Updated curated guidance",
    )


class VoicePersonaResponse(BaseModel):
    """API response for a single voice persona."""

    id: int = Field(description="Database ID of the persona")
    experience_id: str = Field(description="Experience this persona belongs to")
    name: str = Field(description="Display name of the persona")
    instructions: str = Field(description="System-level instructions")
    capabilities: str | None = Field(description="Capabilities description")
    tool_config: str | None = Field(description="Curated guidance JSON")
    is_active: bool = Field(description="Whether the persona is active")
    created_at: datetime = Field(description="When the persona was created")
    updated_at: datetime = Field(description="When the persona was last updated")


class VoicePersonaListResponse(BaseModel):
    """List of voice personas for an experience."""

    personas: list[VoicePersonaResponse]


class VoiceExperienceConfigResponse(BaseModel):
    """API response for a voice experience configuration."""

    id: int = Field(description="Database ID")
    experience_id: str = Field(description="Experience identifier")
    voice_name: str = Field(description="Consistent voice character name")
    synthesized_greeting: str | None = Field(
        description="LLM-generated greeting used on call open"
    )
    greeting_synced_at: datetime | None = Field(
        description="When the greeting was last synthesized"
    )
    created_at: datetime
    updated_at: datetime


class VoiceExperienceConfigUpsertRequest(BaseModel):
    """Payload for creating or updating a voice experience config."""

    voice_name: str = Field(
        min_length=1,
        max_length=128,
        description="Consistent voice character name shown to callers",
    )
