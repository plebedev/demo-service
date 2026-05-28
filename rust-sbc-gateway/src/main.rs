use std::collections::HashSet;
use std::net::{IpAddr, SocketAddr};
use std::str::FromStr;
use std::sync::atomic::Ordering;
use std::sync::Arc;

use anyhow::Context;
use axum::extract::{Path, State, WebSocketUpgrade};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, patch, post};
use axum::{Json, Router};
use futures_util::StreamExt;
use tokio::net::{TcpListener, UdpSocket};
use tokio::sync::{mpsc, Mutex};
use tracing::{info, warn};

use rust_sbc_gateway::config::AppConfig;
use rust_sbc_gateway::metrics::Metrics;
use rust_sbc_gateway::rtp::RtpPacketBuilder;
use rust_sbc_gateway::sip::SipInviteRequest;
use rust_sbc_gateway::sip_engine::{spawn_sip_engine, SipEngineCommand};
use rust_sbc_gateway::state::{CallSession, CallState, SessionRegistry};
use rust_sbc_gateway::ws::{parse_twilio_media_payload, route_media_payload};

#[derive(Clone)]
struct AppState {
    config: AppConfig,
    sessions: SessionRegistry,
    metrics: Arc<Metrics>,
    sip_engine_tx: mpsc::Sender<SipEngineCommand>,
    rtp_ports: Arc<Mutex<RtpPortPool>>,
}

#[derive(Debug)]
struct RtpPortPool {
    start: u16,
    end: u16,
    in_use: HashSet<u16>,
}

impl RtpPortPool {
    fn new(start: u16, end: u16) -> Self {
        Self {
            start,
            end,
            in_use: HashSet::new(),
        }
    }

    fn allocate(&mut self) -> Option<u16> {
        (self.start..=self.end).find(|&port| self.in_use.insert(port))
    }

    fn release(&mut self, port: u16) {
        self.in_use.remove(&port);
    }
}

#[derive(Debug, serde::Deserialize)]
struct CreateSessionRequest {
    session_id: String,
}

#[derive(Debug, serde::Serialize)]
struct SessionResponse {
    session_id: String,
    state: CallState,
}

#[derive(Debug, serde::Deserialize)]
struct UpdateStateRequest {
    state: CallState,
}

#[derive(Debug, serde::Deserialize)]
struct StartTransferRequest {
    session_id: String,
    target_phone: String,
    twilio_number: String,
    trunk_host: String,
    trunk_port: Option<u16>,
    rtp_target_host: Option<String>,
    rtp_target_port: Option<u16>,
}

#[derive(Debug, serde::Serialize)]
struct StartTransferResponse {
    session_id: String,
    state: CallState,
    local_rtp_port: u16,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            std::env::var("RUST_LOG").unwrap_or_else(|_| "rust_sbc_gateway=info,info".to_string()),
        )
        .init();

    let config = AppConfig::from_env();
    if !is_viable_advertise_host(&config.local_sip_advertise_host) {
        warn!(
            advertise_host = %config.local_sip_advertise_host,
            "advertise host is loopback, unspecified, or not an IP; outbound SIP/RTP may fail"
        );
    }
    let metrics = Metrics::shared();
    let sessions = SessionRegistry::new();
    let sip_engine_tx = spawn_sip_engine(config.clone(), metrics.clone())?;

    let state = AppState {
        rtp_ports: Arc::new(Mutex::new(RtpPortPool::new(
            config.rtp_start_port,
            config.rtp_end_port,
        ))),
        config,
        sessions,
        metrics,
        sip_engine_tx,
    };

    let control_app = build_control_router(state.clone());
    let ws_app = build_ws_router(state.clone());

    let control_listener = TcpListener::bind(state.config.control_bind)
        .await
        .with_context(|| format!("bind control listener {}", state.config.control_bind))?;
    let ws_listener = TcpListener::bind(state.config.ws_bind)
        .await
        .with_context(|| format!("bind ws listener {}", state.config.ws_bind))?;

    info!(
        control_bind = %state.config.control_bind,
        ws_bind = %state.config.ws_bind,
        sip_bind = %state.config.sip_bind,
        advertise_host = %state.config.local_sip_advertise_host,
        rtp_start = state.config.rtp_start_port,
        rtp_end = state.config.rtp_end_port,
        "rust-sbc-gateway started"
    );

    let control_server = axum::serve(control_listener, control_app.into_make_service());
    let ws_server = axum::serve(ws_listener, ws_app.into_make_service());

    tokio::try_join!(control_server, ws_server)?;

    Ok(())
}

fn build_control_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/metrics", get(metrics_handler))
        .route("/api/internal/sessions", post(create_session))
        .route(
            "/api/internal/sessions/{session_id}/state",
            patch(update_state),
        )
        .route("/api/internal/transfer/start", post(start_transfer))
        .with_state(state)
}

fn build_ws_router(state: AppState) -> Router {
    Router::new()
        .route("/api/voice/stream", get(ws_stream))
        .with_state(state)
}

async fn health() -> &'static str {
    "ok"
}

async fn metrics_handler(State(state): State<AppState>) -> impl IntoResponse {
    (
        StatusCode::OK,
        [("content-type", "text/plain; version=0.0.4")],
        state.metrics.render_prometheus(),
    )
}

async fn create_session(
    State(state): State<AppState>,
    Json(payload): Json<CreateSessionRequest>,
) -> Json<SessionResponse> {
    let session = CallSession::new(payload.session_id);
    state.sessions.upsert(session.clone()).await;
    Json(SessionResponse {
        session_id: session.session_id,
        state: session.current_state,
    })
}

async fn update_state(
    Path(session_id): Path<String>,
    State(state): State<AppState>,
    Json(payload): Json<UpdateStateRequest>,
) -> Response {
    match state
        .sessions
        .update_state(&session_id, payload.state)
        .await
    {
        Some(session) => Json(SessionResponse {
            session_id: session.session_id,
            state: session.current_state,
        })
        .into_response(),
        None => (StatusCode::NOT_FOUND, "session not found").into_response(),
    }
}

async fn start_transfer(
    State(state): State<AppState>,
    Json(payload): Json<StartTransferRequest>,
) -> Response {
    if !is_viable_advertise_host(&state.config.local_sip_advertise_host) {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            "SBC_ADVERTISE_HOST must be a reachable non-loopback IP address for SIP/RTP",
        )
            .into_response();
    }

    let rtp_port = {
        let mut ports = state.rtp_ports.lock().await;
        match ports.allocate() {
            Some(port) => port,
            None => {
                return (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "no RTP ports available in configured pool",
                )
                    .into_response()
            }
        }
    };

    let mut session = state
        .sessions
        .get(&payload.session_id)
        .await
        .unwrap_or_else(|| CallSession::new(payload.session_id.clone()));

    if let (Some(host), Some(port)) = (&payload.rtp_target_host, payload.rtp_target_port) {
        match SocketAddr::from_str(&format!("{}:{}", host, port)) {
            Ok(remote_addr) => {
                let (tx, rx) = mpsc::channel::<Vec<u8>>(256);
                session.outbound_sip_rtp_tx = Some(tx);
                spawn_rtp_sender(rtp_port, remote_addr, state.metrics.clone(), rx);
            }
            Err(err) => {
                let mut ports = state.rtp_ports.lock().await;
                ports.release(rtp_port);
                return (
                    StatusCode::BAD_REQUEST,
                    format!("invalid RTP target address: {err}"),
                )
                    .into_response();
            }
        }
    }

    session.current_state = CallState::WarmTransferActive;
    state.sessions.upsert(session.clone()).await;

    let invite_request = SipInviteRequest {
        session_id: payload.session_id.clone(),
        target_phone: payload.target_phone,
        twilio_number: payload.twilio_number,
        trunk_host: payload.trunk_host,
        trunk_port: payload
            .trunk_port
            .unwrap_or(state.config.default_trunk_port),
        local_host: state.config.local_sip_advertise_host.clone(),
        local_rtp_port: rtp_port,
    };

    if state
        .sip_engine_tx
        .send(SipEngineCommand::Invite(invite_request))
        .await
        .is_err()
    {
        warn!(session_id = %payload.session_id, "SIP engine unavailable");
        let mut ports = state.rtp_ports.lock().await;
        ports.release(rtp_port);
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            "SIP engine unavailable, try again",
        )
            .into_response();
    }

    Json(StartTransferResponse {
        session_id: payload.session_id,
        state: CallState::WarmTransferActive,
        local_rtp_port: rtp_port,
    })
    .into_response()
}

async fn ws_stream(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
    axum::extract::Query(query): axum::extract::Query<std::collections::HashMap<String, String>>,
) -> Response {
    let session_id = query
        .get("session_id")
        .cloned()
        .unwrap_or_else(|| format!("ws-{}", uuid::Uuid::new_v4()));

    ws.on_upgrade(move |socket| handle_ws(socket, state, session_id))
}

async fn handle_ws(socket: axum::extract::ws::WebSocket, state: AppState, session_id: String) {
    let mut ws_stream = socket;

    let session = state
        .sessions
        .get(&session_id)
        .await
        .unwrap_or_else(|| CallSession::new(session_id.clone()));
    state.sessions.upsert(session).await;

    while let Some(msg_result) = ws_stream.next().await {
        let Ok(msg) = msg_result else {
            state
                .metrics
                .ws_decode_errors_total
                .fetch_add(1, Ordering::Relaxed);
            continue;
        };

        state
            .metrics
            .ws_frames_total
            .fetch_add(1, Ordering::Relaxed);

        let text_frame = match msg {
            axum::extract::ws::Message::Text(text) => text,
            _ => continue,
        };

        let Some(audio_bytes) = parse_twilio_media_payload(&text_frame) else {
            continue;
        };

        state
            .metrics
            .ws_media_frames_total
            .fetch_add(1, Ordering::Relaxed);

        if let Some(session) = state.sessions.get(&session_id).await {
            let _ = route_media_payload(&session, audio_bytes, &state.metrics).await;
        }
    }
}

fn spawn_rtp_sender(
    local_port: u16,
    remote_addr: SocketAddr,
    metrics: Arc<Metrics>,
    mut rx: mpsc::Receiver<Vec<u8>>,
) {
    tokio::spawn(async move {
        let bind_addr = SocketAddr::from(([0, 0, 0, 0], local_port));
        let socket = match UdpSocket::bind(bind_addr).await {
            Ok(socket) => socket,
            Err(err) => {
                warn!(%err, %bind_addr, "failed to bind RTP sender socket");
                return;
            }
        };

        let mut builder = RtpPacketBuilder::new(0, 0, 0x1020_3040);

        while let Some(audio_bytes) = rx.recv().await {
            let packet = builder.build_packet(&audio_bytes);
            match socket.send_to(&packet, remote_addr).await {
                Ok(_) => {
                    metrics
                        .rtp_packets_sent_total
                        .fetch_add(1, Ordering::Relaxed);
                }
                Err(err) => {
                    metrics
                        .udp_send_errors_total
                        .fetch_add(1, Ordering::Relaxed);
                    warn!(%err, %remote_addr, "failed to send RTP packet");
                }
            }
        }
    });
}

fn is_viable_advertise_host(host: &str) -> bool {
    match host.parse::<IpAddr>() {
        Ok(ip) => !ip.is_loopback() && !ip.is_unspecified(),
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use std::net::{IpAddr, Ipv4Addr, SocketAddr};

    use super::*;

    fn test_state() -> AppState {
        let (sip_engine_tx, _sip_engine_rx) = mpsc::channel(1);
        AppState {
            config: AppConfig {
                control_bind: SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 8082),
                ws_bind: SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 8083),
                sip_bind: SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), 5060),
                local_sip_advertise_host: "127.0.0.1".to_string(),
                rtp_start_port: 10000,
                rtp_end_port: 10100,
                default_trunk_port: 5060,
                backend_voice_ws_url: "ws://127.0.0.1:8080/api/voice/stream".to_string(),
                ws_connect_timeout_ms: 3000,
                call_setup_timeout_ms: 7000,
                sip_ringing_enabled: true,
                callsid_prefix: "rust".to_string(),
            },
            sessions: SessionRegistry::new(),
            metrics: Metrics::shared(),
            sip_engine_tx,
            rtp_ports: Arc::new(Mutex::new(RtpPortPool::new(10000, 10100))),
        }
    }

    #[test]
    fn routers_build_without_panicking() {
        let state = test_state();
        let _control = build_control_router(state.clone());
        let _ws = build_ws_router(state);
    }
}
