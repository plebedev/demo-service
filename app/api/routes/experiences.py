"""Experience discovery endpoints."""

from fastapi import APIRouter

from app.schemas.experiences import ExperienceListResponse, available_experiences

router = APIRouter(prefix="/api/experiences", tags=["experiences"])


@router.get("", response_model=ExperienceListResponse)
def list_experiences() -> ExperienceListResponse:
    """Return the demo experiences available in this deployment."""
    return ExperienceListResponse(experiences=available_experiences())
