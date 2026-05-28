use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, Default)]
pub struct Metrics {
    pub ws_frames_total: AtomicU64,
    pub ws_media_frames_total: AtomicU64,
    pub ws_decode_errors_total: AtomicU64,
    pub sip_invites_sent_total: AtomicU64,
    pub sip_responses_total: AtomicU64,
    pub sip_200_ok_total: AtomicU64,
    pub rtp_packets_sent_total: AtomicU64,
    pub rtp_packets_received_total: AtomicU64,
    pub udp_send_errors_total: AtomicU64,
    pub inbound_invites_total: AtomicU64,
    pub inbound_invites_rejected_total: AtomicU64,
    pub inbound_calls_active: AtomicU64,
    pub ws_bridge_connect_failures_total: AtomicU64,
    pub sip_ack_sent_total: AtomicU64,
    pub sip_ack_resend_total: AtomicU64,
    pub sip_bye_requests_total: AtomicU64,
    pub sip_bye_200_sent_total: AtomicU64,
    pub sip_dialog_teardown_clean_total: AtomicU64,
    pub routing_latency_us_total: AtomicU64,
    pub routing_latency_samples_total: AtomicU64,
}

impl Metrics {
    pub fn shared() -> Arc<Self> {
        Arc::new(Self::default())
    }

    pub fn record_routing_latency(&self, latency: Duration) {
        let micros = latency.as_micros() as u64;
        self.routing_latency_us_total
            .fetch_add(micros, Ordering::Relaxed);
        self.routing_latency_samples_total
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn render_prometheus(&self) -> String {
        format!(
            concat!(
                "# HELP sbc_ws_frames_total Total websocket frames seen.\n",
                "# TYPE sbc_ws_frames_total counter\n",
                "sbc_ws_frames_total {}\n",
                "# HELP sbc_ws_media_frames_total Total Twilio media frames decoded.\n",
                "# TYPE sbc_ws_media_frames_total counter\n",
                "sbc_ws_media_frames_total {}\n",
                "# HELP sbc_ws_decode_errors_total Total websocket decode errors.\n",
                "# TYPE sbc_ws_decode_errors_total counter\n",
                "sbc_ws_decode_errors_total {}\n",
                "# HELP sbc_sip_invites_sent_total Total SIP INVITE datagrams sent.\n",
                "# TYPE sbc_sip_invites_sent_total counter\n",
                "sbc_sip_invites_sent_total {}\n",
                "# HELP sbc_sip_responses_total Total SIP responses received.\n",
                "# TYPE sbc_sip_responses_total counter\n",
                "sbc_sip_responses_total {}\n",
                "# HELP sbc_sip_200_ok_total Total SIP 200 OK responses received.\n",
                "# TYPE sbc_sip_200_ok_total counter\n",
                "sbc_sip_200_ok_total {}\n",
                "# HELP sbc_rtp_packets_sent_total Total RTP packets sent.\n",
                "# TYPE sbc_rtp_packets_sent_total counter\n",
                "sbc_rtp_packets_sent_total {}\n",
                "# HELP sbc_rtp_packets_received_total Total RTP packets received.\n",
                "# TYPE sbc_rtp_packets_received_total counter\n",
                "sbc_rtp_packets_received_total {}\n",
                "# HELP sbc_udp_send_errors_total Total UDP send errors.\n",
                "# TYPE sbc_udp_send_errors_total counter\n",
                "sbc_udp_send_errors_total {}\n",
                "# HELP sbc_inbound_invites_total Total inbound SIP INVITEs received.\n",
                "# TYPE sbc_inbound_invites_total counter\n",
                "sbc_inbound_invites_total {}\n",
                "# HELP sbc_inbound_invites_rejected_total Total inbound SIP INVITEs rejected.\n",
                "# TYPE sbc_inbound_invites_rejected_total counter\n",
                "sbc_inbound_invites_rejected_total {}\n",
                "# HELP sbc_inbound_calls_active Current active inbound bridged calls.\n",
                "# TYPE sbc_inbound_calls_active gauge\n",
                "sbc_inbound_calls_active {}\n",
                "# HELP sbc_ws_bridge_connect_failures_total Total backend voice WS connect failures.\n",
                "# TYPE sbc_ws_bridge_connect_failures_total counter\n",
                "sbc_ws_bridge_connect_failures_total {}\n",
                "# HELP sbc_sip_ack_sent_total Total SIP ACK requests sent.\n",
                "# TYPE sbc_sip_ack_sent_total counter\n",
                "sbc_sip_ack_sent_total {}\n",
                "# HELP sbc_sip_ack_resend_total Total SIP ACK requests resent on 2xx retransmissions.\n",
                "# TYPE sbc_sip_ack_resend_total counter\n",
                "sbc_sip_ack_resend_total {}\n",
                "# HELP sbc_sip_bye_requests_total Total inbound SIP BYE requests received.\n",
                "# TYPE sbc_sip_bye_requests_total counter\n",
                "sbc_sip_bye_requests_total {}\n",
                "# HELP sbc_sip_bye_200_sent_total Total 200 OK responses sent for SIP BYE.\n",
                "# TYPE sbc_sip_bye_200_sent_total counter\n",
                "sbc_sip_bye_200_sent_total {}\n",
                "# HELP sbc_sip_dialog_teardown_clean_total Total dialogs closed cleanly.\n",
                "# TYPE sbc_sip_dialog_teardown_clean_total counter\n",
                "sbc_sip_dialog_teardown_clean_total {}\n",
                "# HELP sbc_routing_latency_us_total Sum of frame routing latency in microseconds.\n",
                "# TYPE sbc_routing_latency_us_total counter\n",
                "sbc_routing_latency_us_total {}\n",
                "# HELP sbc_routing_latency_samples_total Number of routing latency samples.\n",
                "# TYPE sbc_routing_latency_samples_total counter\n",
                "sbc_routing_latency_samples_total {}\n"
            ),
            self.ws_frames_total.load(Ordering::Relaxed),
            self.ws_media_frames_total.load(Ordering::Relaxed),
            self.ws_decode_errors_total.load(Ordering::Relaxed),
            self.sip_invites_sent_total.load(Ordering::Relaxed),
            self.sip_responses_total.load(Ordering::Relaxed),
            self.sip_200_ok_total.load(Ordering::Relaxed),
            self.rtp_packets_sent_total.load(Ordering::Relaxed),
            self.rtp_packets_received_total.load(Ordering::Relaxed),
            self.udp_send_errors_total.load(Ordering::Relaxed),
            self.inbound_invites_total.load(Ordering::Relaxed),
            self.inbound_invites_rejected_total.load(Ordering::Relaxed),
            self.inbound_calls_active.load(Ordering::Relaxed),
            self.ws_bridge_connect_failures_total.load(Ordering::Relaxed),
            self.sip_ack_sent_total.load(Ordering::Relaxed),
            self.sip_ack_resend_total.load(Ordering::Relaxed),
            self.sip_bye_requests_total.load(Ordering::Relaxed),
            self.sip_bye_200_sent_total.load(Ordering::Relaxed),
            self.sip_dialog_teardown_clean_total.load(Ordering::Relaxed),
            self.routing_latency_us_total.load(Ordering::Relaxed),
            self.routing_latency_samples_total.load(Ordering::Relaxed),
        )
    }
}
