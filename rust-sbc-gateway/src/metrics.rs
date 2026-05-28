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
    pub udp_send_errors_total: AtomicU64,
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
                "# HELP sbc_udp_send_errors_total Total UDP send errors.\n",
                "# TYPE sbc_udp_send_errors_total counter\n",
                "sbc_udp_send_errors_total {}\n",
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
            self.udp_send_errors_total.load(Ordering::Relaxed),
            self.routing_latency_us_total.load(Ordering::Relaxed),
            self.routing_latency_samples_total.load(Ordering::Relaxed),
        )
    }
}
