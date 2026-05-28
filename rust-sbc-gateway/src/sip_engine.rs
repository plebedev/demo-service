use std::collections::{HashMap, HashSet};
use std::net::{SocketAddr, ToSocketAddrs};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::net::UdpSocket;
use tokio::sync::mpsc;
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::bridge::{
    start_inbound_bridge, InboundBridgeEvent, InboundBridgeHandle, InboundBridgeParams,
};
use crate::config::AppConfig;
use crate::metrics::Metrics;
use crate::sip::{
    build_ack_for_final_response, build_bye_request, build_response_for_in_dialog_request,
    build_sip_200_ok_for_invite, build_sip_final_response_for_invite, build_sip_invite,
    build_sip_ringing_for_invite, build_sip_trying_for_invite, extract_media_addr_from_sdp,
    extract_uri_from_name_addr, parse_sip_request, parse_sip_status_code, parse_sip_status_line,
    response_destination_from_via, sip_header_value, InboundDialogSignaling, SipInvite,
    SipInviteRequest,
};

#[derive(Debug)]
pub enum SipEngineCommand {
    Invite(SipInviteRequest),
}

#[derive(Debug)]
struct OutboundInviteTransaction {
    invite: SipInvite,
    created_at: Instant,
    ack_sent_once: bool,
}

#[derive(Debug)]
struct InboundDialog {
    local_rtp_port: u16,
    signaling: InboundDialogSignaling,
    remote_target_addr: SocketAddr,
    invite_ok_payload: String,
    invite_response_target: SocketAddr,
    bridge: InboundBridgeHandle,
}

#[derive(Debug)]
struct PendingInboundInvite {
    request: crate::sip::SipParsedRequest,
    source_addr: SocketAddr,
    local_tag: String,
    local_rtp_port: u16,
    created_at: Instant,
}

#[derive(Debug)]
struct BoundedRtpPortPool {
    start: u16,
    end: u16,
    in_use: HashSet<u16>,
}

impl BoundedRtpPortPool {
    fn new(start: u16, end: u16) -> Self {
        Self {
            start,
            end,
            in_use: HashSet::new(),
        }
    }

    fn allocate(&mut self) -> Option<u16> {
        (self.start..=self.end).find(|port| self.in_use.insert(*port))
    }

    fn release(&mut self, port: u16) {
        self.in_use.remove(&port);
    }
}

#[derive(Debug)]
struct CachedSipResponse {
    payload: String,
    destination: SocketAddr,
    created_at: Instant,
}

#[derive(Debug)]
enum InternalEngineEvent {
    InboundSetupResult {
        call_id: String,
        result: Result<InboundBridgeHandle, String>,
    },
}

pub fn spawn_sip_engine(
    config: AppConfig,
    metrics: Arc<Metrics>,
) -> anyhow::Result<mpsc::Sender<SipEngineCommand>> {
    let (tx, mut rx) = mpsc::channel::<SipEngineCommand>(128);

    tokio::spawn(async move {
        let socket = match UdpSocket::bind(config.sip_bind).await {
            Ok(socket) => Arc::new(socket),
            Err(err) => {
                error!(%err, sip_bind_addr=%config.sip_bind, "failed to bind SIP socket");
                return;
            }
        };

        info!(sip_bind_addr=%config.sip_bind, "SIP engine started");

        let (bridge_event_tx, mut bridge_event_rx) = mpsc::channel::<InboundBridgeEvent>(128);
        let (internal_event_tx, mut internal_event_rx) = mpsc::channel::<InternalEngineEvent>(128);

        let mut buf = vec![0u8; 8192];
        let mut outbound_invites = HashMap::<String, OutboundInviteTransaction>::new();
        let mut pending_inbound = HashMap::<String, PendingInboundInvite>::new();
        let mut inbound_dialogs = HashMap::<String, InboundDialog>::new();
        let mut recent_bye_responses = HashMap::<String, CachedSipResponse>::new();
        let mut rtp_port_pool = BoundedRtpPortPool::new(config.rtp_start_port, config.rtp_end_port);

        loop {
            tokio::select! {
                maybe_cmd = rx.recv() => {
                    let Some(cmd) = maybe_cmd else {
                        info!("SIP engine command channel closed");
                        break;
                    };

                    match cmd {
                        SipEngineCommand::Invite(request) => {
                            if let Err(err) = handle_outbound_invite(
                                &socket,
                                &metrics,
                                &mut outbound_invites,
                                request,
                            ).await {
                                warn!(%err, "failed handling outbound invite command");
                            }
                        }
                    }
                }
                maybe_event = bridge_event_rx.recv() => {
                    let Some(event) = maybe_event else {
                        continue;
                    };
                    match event {
                        InboundBridgeEvent::BackendEndRequested { call_id } => {
                            if let Some(dialog) = inbound_dialogs.remove(&call_id) {
                                let bye_payload = build_bye_request(&dialog.signaling);
                                if let Err(err) = socket.send_to(bye_payload.as_bytes(), dialog.remote_target_addr).await {
                                    warn!(%err, %call_id, target=%dialog.remote_target_addr, "failed to send SIP BYE after backend end event");
                                } else {
                                    info!(%call_id, target=%dialog.remote_target_addr, "sent SIP BYE after backend end event");
                                }
                                dialog.bridge.stop().await;
                                rtp_port_pool.release(dialog.local_rtp_port);
                                metrics.inbound_calls_active.fetch_sub(1, Ordering::Relaxed);
                                metrics.sip_dialog_teardown_clean_total.fetch_add(1, Ordering::Relaxed);
                            }
                        }
                    }
                }
                maybe_internal = internal_event_rx.recv() => {
                    let Some(event) = maybe_internal else {
                        continue;
                    };
                    match event {
                        InternalEngineEvent::InboundSetupResult { call_id, result } => {
                            let Some(pending) = pending_inbound.remove(&call_id) else {
                                if let Ok(bridge) = result {
                                    let port = bridge.local_rtp_port;
                                    bridge.stop().await;
                                    rtp_port_pool.release(port);
                                }
                                continue;
                            };

                            match result {
                                Ok(bridge_handle) => {
                                    let Some(ok_response) = build_sip_200_ok_for_invite(
                                        &pending.request,
                                        &pending.local_tag,
                                        &config.local_sip_advertise_host,
                                        pending.local_rtp_port,
                                    ) else {
                                        metrics.inbound_invites_rejected_total.fetch_add(1, Ordering::Relaxed);
                                        warn!(%call_id, "failed to build SIP 200 OK for inbound invite");
                                        bridge_handle.stop().await;
                                        rtp_port_pool.release(pending.local_rtp_port);
                                        continue;
                                    };

                                    let invite_response_target = response_target_for_request(
                                        &pending.request,
                                        pending.source_addr,
                                    );

                                    if let Err(err) = socket.send_to(ok_response.as_bytes(), invite_response_target).await {
                                        metrics.udp_send_errors_total.fetch_add(1, Ordering::Relaxed);
                                        warn!(%err, %call_id, %invite_response_target, "failed sending SIP 200 OK for inbound invite");
                                        bridge_handle.stop().await;
                                        rtp_port_pool.release(pending.local_rtp_port);
                                        continue;
                                    }

                                    let local_from = pending
                                        .request
                                        .headers
                                        .get("to")
                                        .map(|value| ensure_tag(value, &pending.local_tag))
                                        .unwrap_or_else(|| format!("<sip:unknown@{}>;tag={}", config.local_sip_advertise_host, pending.local_tag));
                                    let remote_to = pending
                                        .request
                                        .headers
                                        .get("from")
                                        .cloned()
                                        .unwrap_or_else(|| "<sip:unknown@unknown>;tag=remote".to_string());
                                    let remote_request_uri = pending
                                        .request
                                        .headers
                                        .get("contact")
                                        .and_then(|contact| extract_uri_from_name_addr(contact))
                                        .unwrap_or_else(|| pending.request.request_uri.clone());

                                    let signaling = InboundDialogSignaling {
                                        call_id: call_id.clone(),
                                        local_from,
                                        remote_to,
                                        remote_request_uri,
                                        local_host: config.local_sip_advertise_host.clone(),
                                        local_cseq: 1,
                                    };

                                    let remote_target_addr = pending
                                        .request
                                        .headers
                                        .get("contact")
                                        .and_then(|contact| {
                                            parse_sip_target_from_contact(contact, pending.source_addr.port())
                                        })
                                        .unwrap_or(pending.source_addr);
                                    inbound_dialogs.insert(
                                        call_id.clone(),
                                        InboundDialog {
                                            local_rtp_port: pending.local_rtp_port,
                                            signaling,
                                            remote_target_addr,
                                            invite_ok_payload: ok_response,
                                            invite_response_target,
                                            bridge: bridge_handle,
                                        },
                                    );
                                    metrics.inbound_calls_active.fetch_add(1, Ordering::Relaxed);
                                    info!(%call_id, local_rtp_port=pending.local_rtp_port, %invite_response_target, "accepted inbound SIP invite and established backend WS bridge");
                                }
                                Err(reason) => {
                                    metrics.inbound_invites_rejected_total.fetch_add(1, Ordering::Relaxed);
                                    let reject_response = build_sip_final_response_for_invite(
                                        &pending.request,
                                        503,
                                        "Service Unavailable",
                                        &pending.local_tag,
                                    );
                                    if let Some(response) = reject_response {
                                        let target = response_target_for_request(&pending.request, pending.source_addr);
                                        if let Err(err) = socket.send_to(response.as_bytes(), target).await {
                                            metrics.udp_send_errors_total.fetch_add(1, Ordering::Relaxed);
                                            warn!(%err, %call_id, %target, "failed sending SIP 503 rejection for inbound invite");
                                        }
                                    }
                                    rtp_port_pool.release(pending.local_rtp_port);
                                    warn!(%call_id, reason=%reason, "rejected inbound SIP invite");
                                }
                            }
                        }
                    }
                }
                recv_result = socket.recv_from(&mut buf) => {
                    match recv_result {
                        Ok((size, source_addr)) => {
                            let payload = String::from_utf8_lossy(&buf[..size]).to_string();
                            let status_line = parse_sip_status_line(&payload)
                                .unwrap_or_else(|| "<unknown SIP payload>".to_string());

                            if let Some(request) = parse_sip_request(&payload) {
                                handle_inbound_request(
                                    &socket,
                                    &config,
                                    &metrics,
                                    &bridge_event_tx,
                                    &internal_event_tx,
                                    &mut rtp_port_pool,
                                    &mut pending_inbound,
                                    &mut inbound_dialogs,
                                    &mut recent_bye_responses,
                                    request,
                                    payload,
                                    source_addr,
                                ).await;
                            } else if let Some(status_code) = parse_sip_status_code(&payload) {
                                metrics.sip_responses_total.fetch_add(1, Ordering::Relaxed);
                                handle_sip_response(
                                    &socket,
                                    &config,
                                    &metrics,
                                    &mut outbound_invites,
                                    &payload,
                                    source_addr,
                                ).await;
                                if status_code == 200 {
                                    metrics.sip_200_ok_total.fetch_add(1, Ordering::Relaxed);
                                }
                            } else {
                                warn!(%source_addr, %status_line, "received non-SIP payload on SIP socket");
                            }

                            cleanup_stale_state(
                                &mut outbound_invites,
                                &mut pending_inbound,
                                &mut recent_bye_responses,
                            );
                        }
                        Err(err) => {
                            warn!(%err, "failed reading SIP socket");
                        }
                    }
                }
            }
        }
    });

    Ok(tx)
}

async fn handle_outbound_invite(
    socket: &Arc<UdpSocket>,
    metrics: &Arc<Metrics>,
    outbound_invites: &mut HashMap<String, OutboundInviteTransaction>,
    request: SipInviteRequest,
) -> anyhow::Result<()> {
    let invite = build_sip_invite(&request)?;

    socket
        .send_to(invite.payload.as_bytes(), &invite.target_addr)
        .await?;

    metrics
        .sip_invites_sent_total
        .fetch_add(1, Ordering::Relaxed);
    outbound_invites.insert(
        invite.call_id.clone(),
        OutboundInviteTransaction {
            invite: invite.clone(),
            created_at: Instant::now(),
            ack_sent_once: false,
        },
    );

    info!(
        call_id = %invite.call_id,
        target = %invite.target_addr,
        session_id = %request.session_id,
        "sent SIP INVITE"
    );

    Ok(())
}

#[allow(clippy::too_many_arguments)]
async fn handle_inbound_request(
    socket: &Arc<UdpSocket>,
    config: &AppConfig,
    metrics: &Arc<Metrics>,
    bridge_event_tx: &mpsc::Sender<InboundBridgeEvent>,
    internal_event_tx: &mpsc::Sender<InternalEngineEvent>,
    rtp_port_pool: &mut BoundedRtpPortPool,
    pending_inbound: &mut HashMap<String, PendingInboundInvite>,
    inbound_dialogs: &mut HashMap<String, InboundDialog>,
    recent_bye_responses: &mut HashMap<String, CachedSipResponse>,
    request: crate::sip::SipParsedRequest,
    raw_payload: String,
    source_addr: SocketAddr,
) {
    let call_id = request
        .headers
        .get("call-id")
        .cloned()
        .unwrap_or_else(|| "<missing-call-id>".to_string());

    match request.method.as_str() {
        "INVITE" => {
            metrics
                .inbound_invites_total
                .fetch_add(1, Ordering::Relaxed);

            if let Some(dialog) = inbound_dialogs.get(&call_id) {
                if let Err(err) = socket
                    .send_to(
                        dialog.invite_ok_payload.as_bytes(),
                        dialog.invite_response_target,
                    )
                    .await
                {
                    metrics
                        .udp_send_errors_total
                        .fetch_add(1, Ordering::Relaxed);
                    warn!(%err, %call_id, target=%dialog.invite_response_target, "failed re-sending cached SIP 200 OK for duplicate INVITE");
                } else {
                    info!(%call_id, target=%dialog.invite_response_target, "resent cached SIP 200 OK for duplicate INVITE");
                }
                return;
            }

            if pending_inbound.contains_key(&call_id) {
                info!(%call_id, "received duplicate pending INVITE, waiting for setup result");
                return;
            }

            if call_id == "<missing-call-id>" {
                if let Some(response) =
                    build_response_for_in_dialog_request(&raw_payload, 400, "Bad Request")
                {
                    let destination = response_target_for_request(&request, source_addr);
                    let _ = socket.send_to(response.as_bytes(), destination).await;
                }
                return;
            }

            if let Some(trying) = build_sip_trying_for_invite(&request) {
                let target = response_target_for_request(&request, source_addr);
                if let Err(err) = socket.send_to(trying.as_bytes(), target).await {
                    warn!(%err, %call_id, target=%target, "failed sending SIP 100 Trying");
                }
            }

            let local_tag = Uuid::new_v4().simple().to_string();

            if config.sip_ringing_enabled {
                if let Some(ringing) = build_sip_ringing_for_invite(&request, &local_tag) {
                    let target = response_target_for_request(&request, source_addr);
                    if let Err(err) = socket.send_to(ringing.as_bytes(), target).await {
                        warn!(%err, %call_id, target=%target, "failed sending SIP 180 Ringing");
                    }
                }
            }

            let Some(local_rtp_port) = rtp_port_pool.allocate() else {
                metrics
                    .inbound_invites_rejected_total
                    .fetch_add(1, Ordering::Relaxed);
                if let Some(response) = build_sip_final_response_for_invite(
                    &request,
                    503,
                    "Service Unavailable",
                    &Uuid::new_v4().simple().to_string(),
                ) {
                    let target = response_target_for_request(&request, source_addr);
                    let _ = socket.send_to(response.as_bytes(), target).await;
                }
                warn!(%call_id, "rejecting inbound INVITE: RTP port pool exhausted");
                return;
            };

            let Some(remote_media_addr) =
                extract_media_addr_from_sdp(&raw_payload, source_addr.ip())
            else {
                metrics
                    .inbound_invites_rejected_total
                    .fetch_add(1, Ordering::Relaxed);
                if let Some(response) = build_sip_final_response_for_invite(
                    &request,
                    488,
                    "Not Acceptable Here",
                    &local_tag,
                ) {
                    let target = response_target_for_request(&request, source_addr);
                    let _ = socket.send_to(response.as_bytes(), target).await;
                }
                rtp_port_pool.release(local_rtp_port);
                warn!(%call_id, "rejecting inbound INVITE: missing/invalid SDP media address");
                return;
            };

            pending_inbound.insert(
                call_id.clone(),
                PendingInboundInvite {
                    request: request.clone(),
                    source_addr,
                    local_tag: local_tag.clone(),
                    local_rtp_port,
                    created_at: Instant::now(),
                },
            );

            let bridge_event_tx = bridge_event_tx.clone();
            let internal_event_tx = internal_event_tx.clone();
            let backend_voice_ws_url = config.backend_voice_ws_url.clone();
            let ws_connect_timeout_ms = config.ws_connect_timeout_ms;
            let call_setup_timeout_ms = config.call_setup_timeout_ms;
            let callsid_prefix = config.callsid_prefix.clone();
            let metrics_for_bridge = metrics.clone();

            tokio::spawn(async move {
                let uuid_no_dash = Uuid::new_v4().simple().to_string();
                let call_sid = format!("CA{}{}", callsid_prefix, uuid_no_dash);
                let stream_sid = format!("MZ{}", Uuid::new_v4().simple());

                let params = InboundBridgeParams {
                    call_id: call_id.clone(),
                    call_sid,
                    stream_sid,
                    local_tag,
                    local_rtp_port,
                    remote_media_addr,
                    backend_voice_ws_url,
                    ws_connect_timeout_ms,
                };

                let bridge_result = tokio::time::timeout(
                    Duration::from_millis(call_setup_timeout_ms),
                    start_inbound_bridge(params, metrics_for_bridge, bridge_event_tx),
                )
                .await
                .map_err(|_| "call setup timed out before backend bridge was ready".to_string())
                .and_then(|result| result.map_err(|err| err.to_string()));

                let _ = internal_event_tx
                    .send(InternalEngineEvent::InboundSetupResult {
                        call_id,
                        result: bridge_result,
                    })
                    .await;
            });
        }
        "BYE" => {
            metrics
                .sip_bye_requests_total
                .fetch_add(1, Ordering::Relaxed);
            let via = request.headers.get("via").cloned().unwrap_or_default();
            let destination =
                response_destination_from_via(&via, source_addr).unwrap_or(source_addr);
            let cseq = request
                .headers
                .get("cseq")
                .cloned()
                .unwrap_or_else(|| "0 BYE".to_string());
            let cache_key = format!("{}|{}", call_id, cseq);

            if let Some(cached) = recent_bye_responses.get(&cache_key) {
                let _ = socket
                    .send_to(cached.payload.as_bytes(), cached.destination)
                    .await;
                return;
            }

            if let Some(response) = build_response_for_in_dialog_request(&raw_payload, 200, "OK") {
                if let Err(err) = socket.send_to(response.as_bytes(), destination).await {
                    metrics
                        .udp_send_errors_total
                        .fetch_add(1, Ordering::Relaxed);
                    warn!(%err, %call_id, %destination, "failed sending SIP 200 OK for BYE");
                } else {
                    metrics
                        .sip_bye_200_sent_total
                        .fetch_add(1, Ordering::Relaxed);
                    info!(%call_id, %destination, "sent 200 OK for SIP BYE");
                    recent_bye_responses.insert(
                        cache_key,
                        CachedSipResponse {
                            payload: response,
                            destination,
                            created_at: Instant::now(),
                        },
                    );
                }
            }

            if let Some(dialog) = inbound_dialogs.remove(&call_id) {
                dialog.bridge.stop().await;
                rtp_port_pool.release(dialog.local_rtp_port);
                metrics.inbound_calls_active.fetch_sub(1, Ordering::Relaxed);
                metrics
                    .sip_dialog_teardown_clean_total
                    .fetch_add(1, Ordering::Relaxed);
            }
        }
        "CANCEL" => {
            if let Some(response) = build_response_for_in_dialog_request(&raw_payload, 200, "OK") {
                let target = response_target_for_request(&request, source_addr);
                let _ = socket.send_to(response.as_bytes(), target).await;
            }

            if let Some(pending) = pending_inbound.remove(&call_id) {
                if let Some(terminated) = build_sip_final_response_for_invite(
                    &pending.request,
                    487,
                    "Request Terminated",
                    &pending.local_tag,
                ) {
                    let target = response_target_for_request(&pending.request, pending.source_addr);
                    let _ = socket.send_to(terminated.as_bytes(), target).await;
                }
                rtp_port_pool.release(pending.local_rtp_port);
            }
        }
        _ => {
            info!(%source_addr, method=%request.method, %call_id, "received SIP request");
        }
    }
}

async fn handle_sip_response(
    socket: &Arc<UdpSocket>,
    config: &AppConfig,
    metrics: &Arc<Metrics>,
    outbound_invites: &mut HashMap<String, OutboundInviteTransaction>,
    payload: &str,
    source_addr: SocketAddr,
) {
    let Some(status_code) = parse_sip_status_code(payload) else {
        return;
    };
    let status_line =
        parse_sip_status_line(payload).unwrap_or_else(|| "<unknown SIP response>".to_string());

    match status_code {
        code if code < 200 => {
            info!(%source_addr, %status_line, "received provisional SIP response");
        }
        code if code >= 300 => {
            let payload_preview: String = payload.chars().take(300).collect();
            warn!(%source_addr, %status_line, payload_preview=%payload_preview, "received final non-success SIP response");
        }
        _ => {
            info!(%source_addr, %status_line, "received SIP response");
        }
    }

    let Some(call_id) = sip_header_value(payload, "Call-ID") else {
        return;
    };
    let Some(cseq) = sip_header_value(payload, "CSeq") else {
        return;
    };

    let cseq_upper = cseq.to_ascii_uppercase();

    if cseq_upper.contains("INVITE") {
        if let Some(transaction) = outbound_invites.get_mut(&call_id) {
            if let Some(ack) = build_ack_for_final_response(
                payload,
                &transaction.invite,
                source_addr,
                &config.local_sip_advertise_host,
            ) {
                if let Err(err) = socket
                    .send_to(ack.payload.as_bytes(), ack.target_addr)
                    .await
                {
                    metrics
                        .udp_send_errors_total
                        .fetch_add(1, Ordering::Relaxed);
                    warn!(%err, %call_id, target=%ack.target_addr, "failed sending SIP ACK");
                } else if transaction.ack_sent_once {
                    metrics.sip_ack_resend_total.fetch_add(1, Ordering::Relaxed);
                    info!(%call_id, target=%ack.target_addr, status_code=%status_code, "resent SIP ACK for retransmitted final response");
                } else {
                    metrics.sip_ack_sent_total.fetch_add(1, Ordering::Relaxed);
                    info!(%call_id, target=%ack.target_addr, status_code=%status_code, "sent SIP ACK");
                    transaction.ack_sent_once = true;
                }
            }

            if status_code >= 300 {
                outbound_invites.remove(&call_id);
            }
        }
        return;
    }

    if cseq_upper.contains("BYE") && status_code == 200 {
        info!(%call_id, "received SIP 200 OK for locally-sent BYE");
    }
}

fn cleanup_stale_state(
    outbound_invites: &mut HashMap<String, OutboundInviteTransaction>,
    pending_inbound: &mut HashMap<String, PendingInboundInvite>,
    recent_bye_responses: &mut HashMap<String, CachedSipResponse>,
) {
    let now = Instant::now();
    outbound_invites.retain(|_, tx| now.duration_since(tx.created_at) < Duration::from_secs(300));
    pending_inbound
        .retain(|_, invite| now.duration_since(invite.created_at) < Duration::from_secs(60));
    recent_bye_responses
        .retain(|_, cached| now.duration_since(cached.created_at) < Duration::from_secs(300));
}

fn response_target_for_request(
    request: &crate::sip::SipParsedRequest,
    source_addr: SocketAddr,
) -> SocketAddr {
    if let Some(via) = request.headers.get("via") {
        if let Some(destination) = response_destination_from_via(via, source_addr) {
            return destination;
        }
    }
    source_addr
}

fn ensure_tag(value: &str, tag: &str) -> String {
    if value.to_ascii_lowercase().contains(";tag=") {
        value.to_string()
    } else {
        format!("{};tag={}", value, tag)
    }
}

fn parse_sip_target_from_contact(contact: &str, default_port: u16) -> Option<SocketAddr> {
    let uri = extract_uri_from_name_addr(contact)?;
    let uri_without_prefix = uri.strip_prefix("sip:").unwrap_or(&uri);
    let host_port = if let Some((_, host)) = uri_without_prefix.rsplit_once('@') {
        host
    } else {
        uri_without_prefix
    };
    let host_port = host_port.split(';').next().unwrap_or(host_port);

    if let Ok(addr) = host_port.parse::<SocketAddr>() {
        return Some(addr);
    }

    if let Ok(ip) = host_port.parse() {
        return Some(SocketAddr::new(ip, default_port));
    }

    let mut addrs = format!("{}:{}", host_port, default_port)
        .to_socket_addrs()
        .ok()?;
    addrs.next()
}
