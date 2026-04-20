"""System routes for health, readiness, and service status checks."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ExampleRecord
from app.db.session import get_db_session
from app.integrations.status import provider_statuses
from app.schemas.status import ApiStatusResponse, HealthResponse, ReadyResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return a shallow liveness response for the service."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready(db: Session = Depends(get_db_session)) -> ReadyResponse:
    """Verify database connectivity and report backend readiness."""
    db.execute(select(literal(1)))
    return ReadyResponse(status="ready", database_ready=True)


@router.get("/api/status", response_model=ApiStatusResponse)
def api_status(db: Session = Depends(get_db_session)) -> ApiStatusResponse:
    """Return detailed backend status for the frontend BFF."""
    settings = get_settings()
    db.execute(select(literal(1)))
    example_record_count = (
        db.scalar(select(func.count()).select_from(ExampleRecord)) or 0
    )

    return ApiStatusResponse(
        service=settings.app_name,
        environment=settings.environment,
        database_ready=True,
        example_record_count=example_record_count,
        providers=provider_statuses(settings),
    )
