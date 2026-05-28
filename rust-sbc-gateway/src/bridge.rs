use std::net::SocketAddr;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use base64::Engine;
use futures_util::{SinkExt, StreamExt};
use tokio::net::UdpSocket;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;
use tracing::{info, warn};

use crate::metrics::Metrics;
use crate::rtp::RtpPacketBuilder;

#[derive(Debug, Clone)]
pub enum InboundBridgeEvent {
    BackendEndRequested { call_id: String },
}

#[derive(Debug)]
pub struct InboundBridgeHandle {
    pub call_id: String,
    pub call_sid: String,
    pub local_rtp_port: u16,
    pub local_tag: String,
    pub remote_media_addr: SocketAddr,
    pub tasks: Vec<JoinHandle<()>>,
    ws_out_tx: mpsc::Sender<WsOutboundMessage>,
}

impl InboundBridgeHandle {
    pub async fn stop(self) {
        let _ = self.ws_out_tx.send(WsOutboundMessage::StopAndClose).await;
        for task in self.tasks {
            let _ = task.await;
        }
    }
}

#[derive(Debug)]
enum WsOutboundMessage {
    Text(String),
    StopAndClose,
}

#[derive(Debug, serde::Deserialize)]
struct BackendEvent {
    event: String,
    #[serde(default)]
    media: Option<BackendMedia>,
}

#[derive(Debug, serde::Deserialize)]
struct BackendMedia {
    payload: String,
}

pub struct InboundBridgeParams {
    pub call_id: String,
    pub call_sid: String,
    pub stream_sid: String,
    pub local_tag: String,
    pub local_rtp_port: u16,
    pub remote_media_addr: SocketAddr,
    pub backend_voice_ws_url: String,
    pub ws_connect_timeout_ms: u64,
}

pub async fn start_inbound_bridge(
    params: InboundBridgeParams,
    metrics: Arc<Metrics>,
    engine_event_tx: mpsc::Sender<InboundBridgeEvent>,
) -> anyhow::Result<InboundBridgeHandle> {
    let ws_connect_future = connect_async(params.backend_voice_ws_url.as_str());
    let (ws_stream, _response) = tokio::time::timeout(
        Duration::from_millis(params.ws_connect_timeout_ms),
        ws_connect_future,
    )
    .await
    .context("timed out connecting to backend voice websocket")?
    .context("failed to connect backend voice websocket")?;

    let rtp_socket = Arc::new(
        UdpSocket::bind(SocketAddr::from(([0, 0, 0, 0], params.local_rtp_port)))
            .await
            .with_context(|| format!("bind inbound RTP socket on {}", params.local_rtp_port))?,
    );

    let (mut ws_write, mut ws_read) = ws_stream.split();
    let (ws_out_tx, mut ws_out_rx) = mpsc::channel::<WsOutboundMessage>(1024);

    let start_message = serde_json::json!({
        "event": "start",
        "start": {
            "callSid": params.call_sid,
            "streamSid": params.stream_sid,
        }
    });
    ws_out_tx
        .send(WsOutboundMessage::Text(start_message.to_string()))
        .await
        .context("enqueue start event")?;

    let call_id_for_writer = params.call_id.clone();
    let stream_sid_for_writer = params.stream_sid.clone();
    let ws_writer = tokio::spawn(async move {
        while let Some(msg) = ws_out_rx.recv().await {
            match msg {
                WsOutboundMessage::Text(text) => {
                    if ws_write.send(Message::Text(text)).await.is_err() {
                        break;
                    }
                }
                WsOutboundMessage::StopAndClose => {
                    let stop_message = serde_json::json!({
                        "event": "stop",
                        "streamSid": stream_sid_for_writer,
                    });
                    let _ = ws_write.send(Message::Text(stop_message.to_string())).await;
                    let _ = ws_write.close().await;
                    info!(call_id = %call_id_for_writer, "closed backend voice websocket");
                    break;
                }
            }
        }
    });

    let call_id_for_rtp = params.call_id.clone();
    let stream_sid_for_rtp = params.stream_sid.clone();
    let ws_out_tx_for_rtp = ws_out_tx.clone();
    let metrics_for_rtp = metrics.clone();
    let rtp_socket_for_rtp = rtp_socket.clone();
    let remote_media_addr = params.remote_media_addr;
    let rtp_to_ws = tokio::spawn(async move {
        let mut buf = vec![0u8; 4096];
        loop {
            let recv = rtp_socket_for_rtp.recv_from(&mut buf).await;
            let Ok((size, source)) = recv else {
                break;
            };
            if source != remote_media_addr || size < 12 {
                continue;
            }

            let payload = &buf[12..size];
            metrics_for_rtp
                .rtp_packets_received_total
                .fetch_add(1, Ordering::Relaxed);
            let payload_b64 = base64::engine::general_purpose::STANDARD.encode(payload);
            let media_message = serde_json::json!({
                "event": "media",
                "streamSid": stream_sid_for_rtp,
                "media": { "payload": payload_b64 }
            });
            if ws_out_tx_for_rtp
                .send(WsOutboundMessage::Text(media_message.to_string()))
                .await
                .is_err()
            {
                break;
            }
        }
        info!(call_id = %call_id_for_rtp, "stopped RTP->WS bridge");
    });

    let call_id_for_ws = params.call_id.clone();
    let engine_event_tx_for_ws = engine_event_tx.clone();
    let metrics_for_ws = metrics.clone();
    let rtp_socket_for_ws = rtp_socket;
    let remote_media_for_ws = params.remote_media_addr;
    let ws_to_rtp = tokio::spawn(async move {
        let mut rtp_builder = RtpPacketBuilder::new(0, 0, 0x5162_7363);
        while let Some(msg_result) = ws_read.next().await {
            let Ok(msg) = msg_result else {
                break;
            };
            let Message::Text(text) = msg else {
                continue;
            };
            let parsed = serde_json::from_str::<BackendEvent>(&text);
            let Ok(event) = parsed else {
                continue;
            };

            match event.event.as_str() {
                "media" => {
                    let payload_b64 = event.media.map(|m| m.payload).unwrap_or_default();
                    if payload_b64.is_empty() {
                        continue;
                    }
                    let decoded = base64::engine::general_purpose::STANDARD.decode(payload_b64);
                    let Ok(payload) = decoded else {
                        continue;
                    };
                    let packet = rtp_builder.build_packet(&payload);
                    match rtp_socket_for_ws
                        .send_to(&packet, remote_media_for_ws)
                        .await
                    {
                        Ok(_) => {
                            metrics_for_ws
                                .rtp_packets_sent_total
                                .fetch_add(1, Ordering::Relaxed);
                        }
                        Err(err) => {
                            metrics_for_ws
                                .udp_send_errors_total
                                .fetch_add(1, Ordering::Relaxed);
                            warn!(%err, %remote_media_for_ws, "failed sending RTP to remote media");
                        }
                    }
                }
                "clear" => {}
                "end" => {
                    let _ = engine_event_tx_for_ws
                        .send(InboundBridgeEvent::BackendEndRequested {
                            call_id: call_id_for_ws.clone(),
                        })
                        .await;
                    break;
                }
                _ => {}
            }
        }
        info!(call_id = %call_id_for_ws, "stopped WS->RTP bridge");
    });

    Ok(InboundBridgeHandle {
        call_id: params.call_id,
        call_sid: params.call_sid,
        local_rtp_port: params.local_rtp_port,
        local_tag: params.local_tag,
        remote_media_addr: params.remote_media_addr,
        tasks: vec![ws_writer, rtp_to_ws, ws_to_rtp],
        ws_out_tx,
    })
}
