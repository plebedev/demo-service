"""Pydantic schemas for backend readiness and status responses."""

from pydantic import BaseModel

from app.core.phase1 import Phase1Guardrails


class ProviderStatus(BaseModel):
    """Configuration status for a single provider integration."""

    configured: bool


class ProviderStatuses(BaseModel):
    """Grouped provider configuration statuses returned by the API."""

    twilio: ProviderStatus
    plivo: ProviderStatus
    llm: ProviderStatus


class HealthResponse(BaseModel):
    """Shallow health response for process-level checks."""

    status: str


class ReadyResponse(BaseModel):
    """Readiness response for database-backed startup checks."""

    status: str
    database_ready: bool


class ApiStatusResponse(BaseModel):
    """Detailed status response consumed by the frontend BFF."""

    service: str
    environment: str
    database_ready: bool
    example_record_count: int
    providers: ProviderStatuses
    phase1: Phase1Guardrails
    workflow_todo: str
