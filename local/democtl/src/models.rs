use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize, Serialize)]
pub struct InvitationCode {
    pub id: u64,
    pub code: String,
    pub label: Option<String>,
    pub is_active: bool,
    pub max_uses: Option<u32>,
    pub use_count: u32,
    pub created_at: String,
    pub last_used_at: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct InvitationStats {
    pub total_codes: u32,
    pub active_codes: u32,
    pub total_redemptions: u32,
    pub codes: Vec<InvitationCode>,
}

#[derive(Debug, Serialize)]
pub struct CreateInvitationCodeRequest {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    pub label: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_uses: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct RedeemInvitationRequest {
    pub code: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct AccessTokenResponse {
    pub access_token: String,
    pub token_type: String,
    pub experience_id: String,
    pub redirect_path: String,
    pub expires_at: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct AccessTokenVerificationResponse {
    pub status: String,
    pub token_id: String,
    pub experience_id: String,
    pub redirect_path: String,
    pub expires_at: String,
}

#[derive(Debug, Serialize)]
pub struct RunCreateRequest {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_text: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RunResponse {
    pub id: u64,
    pub status: String,
    pub workflow_key: String,
    pub title: Option<String>,
    pub ingestion_summary_json: Option<RunIngestionSummary>,
    pub output_brief_json: Option<Value>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RunListResponse {
    pub runs: Vec<RunResponse>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RunIngestionSummary {
    pub warnings: Vec<String>,
    pub counts: RunIngestionCounts,
    pub accepted_files: Vec<AcceptedRunFileSummary>,
    pub rejected_files: Vec<RejectedRunFile>,
    pub workflow_text_bytes: u64,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RunIngestionCounts {
    pub accepted_files: u32,
    pub rejected_files: u32,
    pub accepted_pasted_text: u32,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct AcceptedRunFileSummary {
    pub file_name: String,
    pub content_type: String,
    pub extracted_text_bytes: u64,
    pub trimmed: bool,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RejectedRunFile {
    pub file_name: String,
    pub content_type: String,
    pub reason: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RunExecutionSummary {
    pub run_id: u64,
    pub status: String,
    pub failure_message: Option<String>,
    pub phase_summary: Vec<String>,
    pub tool_usage_summary: Vec<String>,
    pub handoff_summary: Vec<String>,
    pub audit_summary: Option<String>,
    pub post_processor_summary: Vec<String>,
}

pub type RunEventResponse = Value;
