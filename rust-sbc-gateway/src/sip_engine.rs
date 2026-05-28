use std::sync::atomic::Ordering;
use std::sync::Arc;

use tokio::net::UdpSocket;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::metrics::Metrics;
use crate::sip::{
    build_sip_invite, extract_audio_port_from_sdp, is_sip_200_ok, parse_sip_status_line,
    SipInviteRequest,
};

#[derive(Debug)]
pub enum SipEngineCommand {
    Invite(SipInviteRequest),
}

pub fn spawn_sip_engine(
    sip_bind_addr: std::net::SocketAddr,
    metrics: Arc<Metrics>,
) -> anyhow::Result<mpsc::Sender<SipEngineCommand>> {
    let (tx, mut rx) = mpsc::channel::<SipEngineCommand>(64);

    tokio::spawn(async move {
        let socket = match UdpSocket::bind(sip_bind_addr).await {
            Ok(socket) => socket,
            Err(err) => {
                error!(%err, %sip_bind_addr, "failed to bind SIP socket");
                return;
            }
        };

        info!(%sip_bind_addr, "SIP engine started");

        let mut buf = vec![0u8; 8192];

        loop {
            tokio::select! {
                maybe_cmd = rx.recv() => {
                    let Some(cmd) = maybe_cmd else {
                        info!("SIP engine command channel closed");
                        break;
                    };
                    match cmd {
                        SipEngineCommand::Invite(request) => {
                            match build_sip_invite(&request) {
                                Ok(invite) => {
                                    match socket.send_to(invite.payload.as_bytes(), &invite.target_addr).await {
                                        Ok(_) => {
                                            metrics.sip_invites_sent_total.fetch_add(1, Ordering::Relaxed);
                                            info!(call_id=%invite.call_id, target=%invite.target_addr, session_id=%request.session_id, "sent SIP INVITE");
                                        }
                                        Err(err) => {
                                            metrics.udp_send_errors_total.fetch_add(1, Ordering::Relaxed);
                                            warn!(%err, target=%invite.target_addr, "failed to send SIP INVITE");
                                        }
                                    }
                                }
                                Err(err) => {
                                    warn!(%err, "failed to build SIP INVITE");
                                }
                            }
                        }
                    }
                }
                recv_result = socket.recv_from(&mut buf) => {
                    match recv_result {
                        Ok((size, source_addr)) => {
                            metrics.sip_responses_total.fetch_add(1, Ordering::Relaxed);
                            let text = String::from_utf8_lossy(&buf[..size]);
                            let status_line = parse_sip_status_line(&text)
                                .unwrap_or_else(|| "<unknown SIP response>".to_string());
                            if is_sip_200_ok(&text) {
                                metrics.sip_200_ok_total.fetch_add(1, Ordering::Relaxed);
                                let remote_port = extract_audio_port_from_sdp(&text);
                                info!(
                                    %source_addr,
                                    %status_line,
                                    ?remote_port,
                                    "received SIP response"
                                );
                            } else {
                                let payload_preview: String = text.chars().take(300).collect();
                                warn!(
                                    %source_addr,
                                    %status_line,
                                    payload_preview=%payload_preview,
                                    "received non-200 SIP response"
                                );
                            }
                        }
                        Err(err) => {
                            warn!(%err, "failed to read SIP socket");
                        }
                    }
                }
            }
        }
    });

    Ok(tx)
}
