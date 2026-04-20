from pydantic import BaseModel


class ProviderStatus(BaseModel):
    configured: bool


class ProviderStatuses(BaseModel):
    twilio: ProviderStatus
    plivo: ProviderStatus
    llm: ProviderStatus


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    database_ready: bool


class ApiStatusResponse(BaseModel):
    service: str
    environment: str
    database_ready: bool
    example_record_count: int
    providers: ProviderStatuses
