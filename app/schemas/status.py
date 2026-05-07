"""Pydantic schemas for backend readiness and status responses."""

from pydantic import BaseModel, Field

from app.core.phase1 import Phase1Guardrails


class ProviderStatus(BaseModel):
    """Configuration status for a single provider integration."""

    configured: bool = Field(
        description="True when the provider's required credentials are present"
    )


class ProviderStatuses(BaseModel):
    """Grouped provider configuration statuses returned by the API."""

    twilio: ProviderStatus = Field(description="Twilio SMS provider status")
    plivo: ProviderStatus = Field(description="Plivo SMS provider status")
    openai: ProviderStatus = Field(description="OpenAI provider status")
    anthropic: ProviderStatus = Field(description="Anthropic provider status")


class HealthResponse(BaseModel):
    """Shallow health response for process-level checks."""

    status: str = Field(description="Always 'ok' when the process is running")


class ReadyResponse(BaseModel):
    """Readiness response for database-backed startup checks."""

    status: str = Field(
        description="'ok' when the database is reachable, 'not_ready' otherwise"
    )
    database_ready: bool = Field(
        description="True when the database connection and migrations are healthy"
    )


class ApiStatusResponse(BaseModel):
    """Detailed status response consumed by the frontend BFF."""

    service: str = Field(description="Service name identifier")
    environment: str = Field(
        description="Deployment environment (e.g. 'production', 'local')"
    )
    database_ready: bool = Field(
        description="True when the database connection is healthy"
    )
    example_record_count: int = Field(
        description="Number of example records in the database; used as a readiness signal"
    )
    providers: ProviderStatuses = Field(
        description="Configuration status for each external provider"
    )
    features: dict[str, bool] = Field(
        description="Feature flag map for the current deployment"
    )
    phase1: Phase1Guardrails = Field(
        description="Phase-1 guardrail settings active for this deployment"
    )
    workflow_todo: str = Field(
        description="Placeholder field indicating pending workflow configuration"
    )
