"""Schemas for demo experience discovery."""

from pydantic import BaseModel, Field

from app.core.experiences import (
    EXPERIENCE_DESCRIPTIONS,
    EXPERIENCE_LABELS,
    EXPERIENCE_ROUTES,
    ExperienceId,
)


class ExperienceResponse(BaseModel):
    """Public metadata for one available demo experience."""

    id: ExperienceId = Field(description="Stable identifier for the experience")
    label: str = Field(description="Short display label shown in the UI")
    description: str = Field(
        description="Human-readable description of the experience's purpose"
    )
    route: str = Field(description="Frontend route path for this experience")
    available: bool = Field(
        default=True, description="False when the experience is temporarily disabled"
    )
    invite_request_available: bool = Field(
        default=True,
        description="False when invite requests are closed for this experience",
    )


class ExperienceListResponse(BaseModel):
    """Available demo experiences for the frontend access hub."""

    experiences: list[ExperienceResponse] = Field(
        description="All configured experiences in display order"
    )


def available_experiences() -> list[ExperienceResponse]:
    """Return the deployment's configured experience registry."""
    return [
        ExperienceResponse(
            id=experience_id,
            label=EXPERIENCE_LABELS[experience_id],
            description=EXPERIENCE_DESCRIPTIONS[experience_id],
            route=EXPERIENCE_ROUTES[experience_id],
        )
        for experience_id in ExperienceId
    ]
