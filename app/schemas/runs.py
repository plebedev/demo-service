"""Pydantic schemas for persisted demo runs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.run import RunStatus


class RunInputMetadata(BaseModel):
    """Structured metadata describing the accepted run input."""

    source_kind: str
    accepted_file_count: int
    rejected_file_count: int
    warning_count: int


class UploadedRunFile(BaseModel):
    """Accepted uploaded file and its extracted text."""

    file_name: str
    content_type: str
    file_size_bytes: int
    extracted_text: str
    extracted_text_bytes: int
    trimmed: bool


class AcceptedRunFileSummary(BaseModel):
    """Summary metadata for one accepted file."""

    file_name: str
    content_type: str
    file_size_bytes: int
    extracted_text_bytes: int
    trimmed: bool


class RejectedRunFile(BaseModel):
    """Rejected file summary with an honest reason."""

    file_name: str
    content_type: str
    reason: str


class RunIngestionCounts(BaseModel):
    """Count summary for the last ingestion pass."""

    accepted_files: int
    rejected_files: int
    trimmed_files: int
    accepted_pasted_text: int
    trimmed_pasted_text: int


class RunIngestionLimits(BaseModel):
    """Configured deterministic limits for the demo ingestion path."""

    max_files_per_run: int
    max_file_size_bytes: int
    max_extracted_text_bytes: int
    max_total_workflow_text_bytes: int
    max_pasted_text_bytes: int
    strategy: str


class RunIngestionSummary(BaseModel):
    """Detailed result of the last deterministic ingestion pass."""

    warnings: list[str]
    counts: RunIngestionCounts
    accepted_files: list[AcceptedRunFileSummary]
    rejected_files: list[RejectedRunFile]
    limits: RunIngestionLimits
    workflow_text_bytes: int


class RunCreateRequest(BaseModel):
    """Request body for creating a new run."""

    title: str | None = Field(default=None, max_length=255)
    input_text: str | None = None


class RunUpdateRequest(BaseModel):
    """Request body for updating the editable draft fields of a run."""

    title: str | None = Field(default=None, max_length=255)
    input_text: str | None = None
    input_metadata_json: RunInputMetadata | None = None


class RunSubmitRequest(BaseModel):
    """Optional data accepted when a run is submitted."""

    title: str | None = Field(default=None, max_length=255)
    input_text: str | None = None
    input_metadata_json: RunInputMetadata | None = None


class RunResponse(BaseModel):
    """Serialized run record returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: RunStatus
    workflow_key: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    input_text: str | None
    normalized_input_text: str | None
    input_metadata_json: RunInputMetadata | None
    uploaded_files_json: list[UploadedRunFile] | None
    ingestion_summary_json: RunIngestionSummary | None
    output_brief_json: dict[str, object] | None
    post_processor_results_json: dict[str, object] | None
    follow_up_count: int


class RunListResponse(BaseModel):
    """Simple list wrapper for newest-first run history."""

    runs: list[RunResponse]
