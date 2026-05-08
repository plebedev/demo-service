use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize)]
pub struct HealthResponse {
    pub status: String,
    pub service: String,
}

impl HealthResponse {
    pub fn ok() -> Self {
        Self {
            status: "ok".to_owned(),
            service: "demo-text-tools".to_owned(),
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct NormalizeRequest {
    pub text: String,
}

#[derive(Debug, Serialize)]
pub struct NormalizeResponse {
    pub text: String,
    pub input_bytes: usize,
    pub output_bytes: usize,
    pub changed: bool,
}

#[derive(Debug, Deserialize)]
pub struct ChunkRequest {
    pub text: String,
    pub chunk_size: usize,
    pub chunk_overlap: usize,
}

#[derive(Debug, Serialize)]
pub struct ChunkResponse {
    pub chunks: Vec<TextChunk>,
}

#[derive(Debug, Serialize)]
pub struct TextChunk {
    pub index: usize,
    pub text: String,
    pub bytes: usize,
}

#[derive(Debug, Deserialize)]
pub struct InspectInputRequest {
    pub file_name: String,
    pub content_type: String,
    pub size_bytes: usize,
}

#[derive(Debug, Serialize)]
pub struct InspectInputResponse {
    pub accepted: bool,
    pub kind: InputKind,
    pub reason: Option<String>,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum InputKind {
    Text,
    Pdf,
    Image,
    Audio,
    Video,
    Empty,
    Unsupported,
}

#[derive(Debug, Serialize)]
pub struct ErrorResponse {
    pub detail: String,
}
