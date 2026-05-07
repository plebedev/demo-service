"""Schemas for demo experience discovery."""

from pydantic import BaseModel

from app.core.experiences import (
    EXPERIENCE_DESCRIPTIONS,
    EXPERIENCE_LABELS,
    EXPERIENCE_ROUTES,
    ExperienceId,
)


class ExperienceResponse(BaseModel):
    """Public metadata for one available demo experience."""

    id: ExperienceId
    label: str
    description: str
    route: str
    available: bool = True
    invite_request_available: bool = True


class ExperienceListResponse(BaseModel):
    """Available demo experiences for the frontend access hub."""

    experiences: list[ExperienceResponse]


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
