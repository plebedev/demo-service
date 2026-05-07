"""Pydantic schemas for persisted demo runs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.run import RunStatus


class RunInputMetadata(BaseModel):
    """Structured metadata describing the accepted run input."""

    source_kind: str = Field(
        description="Input source type: 'text', 'files', or 'mixed'"
    )
    accepted_file_count: int = Field(
        description="Number of files that passed validation"
    )
    rejected_file_count: int = Field(
        description="Number of files that failed validation"
    )
    warning_count: int = Field(
        description="Number of non-fatal warnings emitted during ingestion"
    )


class UploadedRunFile(BaseModel):
    """Accepted uploaded file and its extracted text."""

    file_name: str = Field(description="Original filename from the upload")
    content_type: str = Field(description="MIME type of the uploaded file")
    file_size_bytes: int = Field(description="Raw file size in bytes")
    extracted_text: str = Field(description="Text extracted from the file")
    extracted_text_bytes: int = Field(description="Byte length of the extracted text")
    trimmed: bool = Field(
        description="True when the extracted text was truncated to fit the configured limit"
    )


class AcceptedRunFileSummary(BaseModel):
    """Summary metadata for one accepted file."""

    file_name: str = Field(description="Original filename from the upload")
    content_type: str = Field(description="MIME type of the uploaded file")
    file_size_bytes: int = Field(description="Raw file size in bytes")
    extracted_text_bytes: int = Field(description="Byte length of the extracted text")
    trimmed: bool = Field(
        description="True when the extracted text was truncated to fit the configured limit"
    )


class RejectedRunFile(BaseModel):
    """Rejected file summary with an honest reason."""

    file_name: str = Field(description="Original filename from the upload")
    content_type: str = Field(description="MIME type of the rejected file")
    reason: str = Field(
        description="Human-readable explanation of why the file was rejected"
    )


class RunIngestionCounts(BaseModel):
    """Count summary for the last ingestion pass."""

    accepted_files: int = Field(description="Number of files that passed validation")
    rejected_files: int = Field(description="Number of files that failed validation")
    trimmed_files: int = Field(
        description="Number of accepted files whose text was truncated"
    )
    accepted_pasted_text: int = Field(
        description="1 if pasted text was accepted, 0 otherwise"
    )
    trimmed_pasted_text: int = Field(
        description="1 if pasted text was truncated, 0 otherwise"
    )


class RunIngestionLimits(BaseModel):
    """Configured deterministic limits for the demo ingestion path."""

    max_files_per_run: int = Field(
        description="Maximum number of files allowed per run"
    )
    max_file_size_bytes: int = Field(
        description="Maximum allowed raw file size in bytes"
    )
    max_extracted_text_bytes: int = Field(
        description="Maximum extracted text bytes per file"
    )
    max_total_workflow_text_bytes: int = Field(
        description="Maximum combined text bytes passed to the workflow"
    )
    max_pasted_text_bytes: int = Field(
        description="Maximum allowed pasted text input size in bytes"
    )
    strategy: str = Field(description="Active ingestion strategy identifier")


class RunIngestionSummary(BaseModel):
    """Detailed result of the last deterministic ingestion pass."""

    warnings: list[str] = Field(
        description="Non-fatal warning messages emitted during ingestion"
    )
    counts: RunIngestionCounts = Field(
        description="Aggregate counts from the ingestion pass"
    )
    accepted_files: list[AcceptedRunFileSummary] = Field(
        description="Metadata for each file that passed validation"
    )
    rejected_files: list[RejectedRunFile] = Field(
        description="Metadata and rejection reason for each failed file"
    )
    limits: RunIngestionLimits = Field(
        description="Configured limits that were applied during this ingestion"
    )
    workflow_text_bytes: int = Field(
        description="Total byte length of text that will be passed to the workflow"
    )


class RunCreateRequest(BaseModel):
    """Request body for creating a new run."""

    title: str | None = Field(
        default=None, max_length=255, description="Optional display title for the run"
    )
    input_text: str | None = Field(
        default=None, description="Optional initial pasted text input"
    )


class RunUpdateRequest(BaseModel):
    """Request body for updating the editable draft fields of a run."""

    title: str | None = Field(
        default=None, max_length=255, description="Updated display title"
    )
    input_text: str | None = Field(
        default=None, description="Updated pasted text input"
    )
    input_metadata_json: RunInputMetadata | None = Field(
        default=None, description="Updated ingestion metadata"
    )


class RunSubmitRequest(BaseModel):
    """Optional data accepted when a run is submitted."""

    title: str | None = Field(
        default=None,
        max_length=255,
        description="Optional display title at submission time",
    )
    input_text: str | None = Field(default=None, description="Final pasted text input")
    input_metadata_json: RunInputMetadata | None = Field(
        default=None, description="Final ingestion metadata"
    )


class SampleChaosSet(BaseModel):
    """Curated sample notes users can load into a run."""

    key: str = Field(description="Stable identifier for this sample set")
    title: str = Field(description="Display title shown in the sample picker")
    description: str = Field(
        description="Short description of the sample's content and purpose"
    )
    notes: list[str] = Field(
        description="Individual note strings that make up the sample"
    )


class SampleChaosListResponse(BaseModel):
    """Protected sample-set catalog response."""

    samples: list[SampleChaosSet] = Field(
        description="Available sample sets ordered for display"
    )


class SampleChaosApplyRequest(BaseModel):
    """Request for applying a curated sample set to a run."""

    sample_key: str = Field(
        min_length=1, description="Key of the sample set to load into the run"
    )


class FollowUpRequest(BaseModel):
    """One guarded follow-up question about the generated brief."""

    question: str = Field(
        min_length=3,
        max_length=500,
        description="Follow-up question text submitted by the user",
    )


class FollowUpResponse(BaseModel):
    """Stored answer for the single allowed follow-up."""

    question: str = Field(description="The follow-up question as submitted")
    answer: str = Field(description="LLM-generated answer to the question")
    category: str = Field(description="Category label assigned to this follow-up")


class NotificationPreference(BaseModel):
    """Captured notification preference for a run."""

    wants_sms: bool = Field(
        description="True when the user opted in to SMS notification"
    )
    phone_number: str | None = Field(
        default=None, description="E.164-formatted phone number for SMS delivery"
    )
    phone_number_blocked: bool = Field(
        default=False,
        description="True when the phone number appears on the permanent block list",
    )


class NotificationPreferenceRequest(BaseModel):
    """Request body for storing notification preference."""

    wants_sms: bool = Field(
        description="True when the user opts in to SMS notification"
    )
    phone_number: str | None = Field(
        default=None,
        max_length=32,
        description="E.164-formatted phone number; required when wants_sms is True",
    )


class SmsPhoneStatusRequest(BaseModel):
    """Request body for checking SMS phone status."""

    phone_number: str | None = Field(
        default=None,
        max_length=32,
        description="E.164-formatted phone number to check",
    )


class SmsPhoneStatusResponse(BaseModel):
    """Validation and permanent block-list status for one phone number."""

    valid: bool = Field(description="True when the number passes format validation")
    phone_number: str | None = Field(
        description="Normalized phone number, or null if invalid"
    )
    phone_number_blocked: bool = Field(
        description="True when the number appears on the permanent SMS block list"
    )


class RunResponse(BaseModel):
    """Serialized run record returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Database ID of the run")
    status: RunStatus = Field(description="Current lifecycle status of the run")
    workflow_key: str = Field(description="Workflow variant identifier")
    title: str | None = Field(description="Optional display title")
    created_at: datetime = Field(description="Timestamp when the run was created")
    updated_at: datetime = Field(description="Timestamp of the last update")
    submitted_at: datetime | None = Field(
        description="Timestamp when the run was submitted for processing"
    )
    completed_at: datetime | None = Field(
        description="Timestamp when the run completed successfully"
    )
    failed_at: datetime | None = Field(
        description="Timestamp when the run entered the failed state"
    )
    failure_message: str | None = Field(description="User-facing failure explanation")
    failure_internal_reason: str | None = Field(
        description="Internal operator-facing failure detail"
    )
    input_text: str | None = Field(description="Raw pasted text provided by the user")
    normalized_input_text: str | None = Field(
        description="Cleaned and normalized version of the input text used by the workflow"
    )
    input_metadata_json: RunInputMetadata | None = Field(
        description="Structured ingestion metadata for the run's input"
    )
    uploaded_files_json: list[UploadedRunFile] | None = Field(
        description="Accepted uploaded files with their extracted text"
    )
    ingestion_summary_json: RunIngestionSummary | None = Field(
        description="Full result of the last ingestion pass"
    )
    output_brief_json: dict[str, object] | None = Field(
        description="Structured workflow output brief"
    )
    post_processor_results_json: dict[str, object] | None = Field(
        description="Keyed results from post-processor steps"
    )
    follow_up_count: int = Field(
        description="Number of follow-up questions submitted for this run"
    )
    follow_up_response_json: FollowUpResponse | None = Field(
        description="Stored follow-up question and answer"
    )
    notification_preference_json: NotificationPreference | None = Field(
        description="User's SMS notification preference for this run"
    )


class RunListResponse(BaseModel):
    """Simple list wrapper for newest-first run history."""

    runs: list[RunResponse] = Field(
        description="Runs belonging to this invitation code, ordered newest-first"
    )


class RunExecutionSummary(BaseModel):
    """Concise operator-friendly summary of one run execution."""

    run_id: int = Field(description="Database ID of the run")
    status: RunStatus = Field(description="Final status of the run")
    failure_message: str | None = Field(
        description="User-facing failure message if the run failed"
    )
    phase_summary: list[str] = Field(
        description="Human-readable summary lines for each workflow phase"
    )
    tool_usage_summary: list[str] = Field(
        description="Summary of tool calls made during the run"
    )
    handoff_summary: list[str] = Field(
        description="Summary of agent handoffs that occurred"
    )
    audit_summary: str | None = Field(
        description="Optional consolidated audit note for the run"
    )
    post_processor_summary: list[str] = Field(
        description="Summary lines for each post-processor that ran"
    )
