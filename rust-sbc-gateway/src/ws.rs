use std::sync::Arc;
use std::time::Instant;

use base64::Engine;
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message;

use crate::metrics::Metrics;
use crate::state::{CallSession, CallState};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RoutingDecision {
    SentToAi,
    DroppedDuringWarmTransfer,
    SentToOutboundSip,
    NoRoute,
}

#[derive(Debug, serde::Deserialize)]
struct TwilioFrame {
    event: String,
    media: Option<TwilioMedia>,
}

#[derive(Debug, serde::Deserialize)]
struct TwilioMedia {
    payload: String,
}

pub fn parse_twilio_media_payload(frame_text: &str) -> Option<Vec<u8>> {
    let frame: TwilioFrame = serde_json::from_str(frame_text).ok()?;
    if frame.event != "media" {
        return None;
    }
    let media = frame.media?;
    base64::engine::general_purpose::STANDARD
        .decode(media.payload)
        .ok()
}

pub fn extract_text_frame(message: &Message) -> Option<&str> {
    match message {
        Message::Text(text) => Some(text.as_ref()),
        _ => None,
    }
}

pub async fn route_media_payload(
    session: &CallSession,
    audio_payload: Vec<u8>,
    metrics: &Arc<Metrics>,
) -> RoutingDecision {
    let started = Instant::now();

    let decision = match session.current_state {
        CallState::NormalCall => {
            if let Some(tx) = &session.ai_engine_tx {
                if send_payload(tx, audio_payload).await {
                    RoutingDecision::SentToAi
                } else {
                    RoutingDecision::NoRoute
                }
            } else {
                RoutingDecision::NoRoute
            }
        }
        CallState::WarmTransferActive => RoutingDecision::DroppedDuringWarmTransfer,
        CallState::TransferComplete => {
            if let Some(tx) = &session.outbound_sip_rtp_tx {
                if send_payload(tx, audio_payload).await {
                    RoutingDecision::SentToOutboundSip
                } else {
                    RoutingDecision::NoRoute
                }
            } else {
                RoutingDecision::NoRoute
            }
        }
    };

    metrics.record_routing_latency(started.elapsed());
    decision
}

async fn send_payload(tx: &mpsc::Sender<Vec<u8>>, payload: Vec<u8>) -> bool {
    tx.send(payload).await.is_ok()
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use base64::Engine;
    use tokio::sync::mpsc;

    use crate::metrics::Metrics;
    use crate::state::{CallSession, CallState};

    use super::{parse_twilio_media_payload, route_media_payload, RoutingDecision};

    #[test]
    fn parses_twilio_media_payload() {
        let payload = base64::engine::general_purpose::STANDARD.encode([1u8, 2, 3]);
        let frame = format!(
            "{{\"event\":\"media\",\"media\":{{\"payload\":\"{}\"}}}}",
            payload
        );
        let decoded = parse_twilio_media_payload(&frame).expect("payload should decode");
        assert_eq!(decoded, vec![1, 2, 3]);
    }

    #[tokio::test]
    async fn routes_to_ai_in_normal_state() {
        let (ai_tx, mut ai_rx) = mpsc::channel(1);
        let metrics = Arc::new(Metrics::default());

        let mut session = CallSession::new("abc");
        session.current_state = CallState::NormalCall;
        session.ai_engine_tx = Some(ai_tx);

        let decision = route_media_payload(&session, vec![7, 8, 9], &metrics).await;
        assert_eq!(decision, RoutingDecision::SentToAi);
        assert_eq!(ai_rx.recv().await, Some(vec![7, 8, 9]));
    }

    #[tokio::test]
    async fn drops_during_warm_transfer() {
        let metrics = Arc::new(Metrics::default());

        let mut session = CallSession::new("abc");
        session.current_state = CallState::WarmTransferActive;

        let decision = route_media_payload(&session, vec![7, 8, 9], &metrics).await;
        assert_eq!(decision, RoutingDecision::DroppedDuringWarmTransfer);
    }

    #[tokio::test]
    async fn routes_to_outbound_after_transfer() {
        let (sip_tx, mut sip_rx) = mpsc::channel(1);
        let metrics = Arc::new(Metrics::default());

        let mut session = CallSession::new("abc");
        session.current_state = CallState::TransferComplete;
        session.outbound_sip_rtp_tx = Some(sip_tx);

        let decision = route_media_payload(&session, vec![1, 2], &metrics).await;
        assert_eq!(decision, RoutingDecision::SentToOutboundSip);
        assert_eq!(sip_rx.recv().await, Some(vec![1, 2]));
    }
}
