use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::net::UdpSocket;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::metrics::Metrics;
use crate::sip::{
    build_ack_for_final_response, build_sip_invite, extract_audio_port_from_sdp, is_sip_200_ok,
    parse_sip_status_code, parse_sip_status_line, sip_header_value, SipInvite, SipInviteRequest,
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
        let mut invite_transactions =
            std::collections::HashMap::<String, (SipInvite, Instant)>::new();

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
                                            invite_transactions.insert(
                                                invite.call_id.clone(),
                                                (invite.clone(), Instant::now()),
                                            );
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
                            let status_code = parse_sip_status_code(&text);

                            match status_code {
                                Some(code) if code < 200 => {
                                    info!(%source_addr, %status_line, "received provisional SIP response");
                                }
                                Some(code) if code == 200 && is_sip_200_ok(&text) => {
                                    metrics.sip_200_ok_total.fetch_add(1, Ordering::Relaxed);
                                    let remote_port = extract_audio_port_from_sdp(&text);
                                    info!(
                                        %source_addr,
                                        %status_line,
                                        ?remote_port,
                                        "received SIP 200 OK response"
                                    );
                                }
                                Some(code) if code >= 300 => {
                                    let payload_preview: String = text.chars().take(300).collect();
                                    warn!(
                                        %source_addr,
                                        %status_line,
                                        payload_preview=%payload_preview,
                                        "received final non-success SIP response"
                                    );
                                }
                                Some(_) | None => {
                                    info!(%source_addr, %status_line, "received SIP response");
                                }
                            }

                            if let (Some(code), Some(call_id), Some(cseq)) = (
                                status_code,
                                sip_header_value(&text, "Call-ID"),
                                sip_header_value(&text, "CSeq"),
                            ) {
                                let is_invite_tx = cseq.to_ascii_uppercase().contains("INVITE");
                                if is_invite_tx && code >= 200 {
                                    if let Some((invite, _)) = invite_transactions.get(&call_id) {
                                        if let Some(ack) = build_ack_for_final_response(&text, invite) {
                                            if let Err(err) = socket.send_to(ack.as_bytes(), source_addr).await {
                                                warn!(%err, %source_addr, %call_id, "failed to send SIP ACK");
                                            } else {
                                                info!(%source_addr, %call_id, status_code = code, "sent SIP ACK");
                                            }
                                        }
                                    }
                                }

                                if code >= 200 {
                                    invite_transactions.remove(&call_id);
                                }
                            }

                            // Best-effort cleanup for stale invites in case we never see a final response.
                            if invite_transactions.len() > 1024 {
                                let now = Instant::now();
                                invite_transactions.retain(|_, (_, created_at)| {
                                    now.duration_since(*created_at) < Duration::from_secs(300)
                                });
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
