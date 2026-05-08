use axum::extract::Json;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::Router;

use crate::models::{
    ChunkRequest, ChunkResponse, ErrorResponse, HealthResponse, InspectInputRequest,
    InspectInputResponse, NormalizeRequest,
};
use crate::text::{chunk_text, inspect_input, normalize_text};
use tracing::info;

pub fn router() -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/v1/text/normalize", post(normalize))
        .route("/v1/text/chunk", post(chunk))
        .route("/v1/input/inspect", post(inspect))
}

async fn health() -> Json<HealthResponse> {
    Json(HealthResponse::ok())
}

async fn normalize(Json(payload): Json<NormalizeRequest>) -> impl IntoResponse {
    Json(normalize_text(&payload.text))
}

async fn chunk(Json(payload): Json<ChunkRequest>) -> Result<Json<ChunkResponse>, ApiError> {
    let input_bytes = payload.text.len();
    let chunk_size = payload.chunk_size;
    let chunk_overlap = payload.chunk_overlap;
    let chunks = chunk_text(&payload.text, payload.chunk_size, payload.chunk_overlap)
        .map_err(|err| ApiError::bad_request(err.to_string()))?;
    info!(
        input_bytes,
        chunk_size,
        chunk_overlap,
        chunk_count = chunks.len(),
        "text chunked"
    );
    Ok(Json(ChunkResponse { chunks }))
}

async fn inspect(Json(payload): Json<InspectInputRequest>) -> Json<InspectInputResponse> {
    Json(inspect_input(&payload))
}

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    detail: String,
}

impl ApiError {
    fn bad_request(detail: String) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            detail,
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(ErrorResponse {
                detail: self.detail,
            }),
        )
            .into_response()
    }
}
