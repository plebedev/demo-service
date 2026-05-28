# rust-sbc-gateway

Infrastructure-only SIP/RTP SBC/B2BUA experiment service for warm transfer prototyping.

## Scope (Phase 1)

- UDP SIP signaling engine on port `5060`
- RTP sender support on configurable UDP range (default `10000-10100`)
- WebSocket ingest endpoint (`/api/voice/stream`) that parses Twilio-style media frames
- Central in-memory call session state registry
- Internal control API to create sessions, update state, and start transfer attempts
- Prometheus-compatible metrics endpoint (`/metrics`)
- Inbound SIP (UAS) handling for Elastic SIP Trunk Origination
- Twilio-style backend WebSocket bridge (`start/media/stop`, consume `media/clear/end`)
- SIP dialog closure handling for ACK/BYE/CANCEL with retransmit-safe responses

## Endpoints

- `GET /health`
- `GET /metrics`
- `POST /api/internal/sessions`
- `PATCH /api/internal/sessions/{session_id}/state`
- `POST /api/internal/transfer/start`
- `GET /api/voice/stream?session_id=<id>` (WebSocket)

## Environment variables

- `SBC_CONTROL_BIND` (default `0.0.0.0:8082`)
- `SBC_WS_BIND` (default `0.0.0.0:8083`)
- `SBC_SIP_BIND` (default `0.0.0.0:5060`)
- `SBC_ADVERTISE_HOST` (optional; hostname resolves to IPv4, but for Twilio use a public IPv4 literal)
- `SBC_RTP_START_PORT` (default `10000`)
- `SBC_RTP_END_PORT` (default `10100`)
- `SBC_TRUNK_PORT` (default `5060`)
- `SBC_BACKEND_VOICE_WS_URL` (default `wss://demo.lebedev.ai/api/voice/stream`)
- `SBC_WS_CONNECT_TIMEOUT_MS` (default `3000`)
- `SBC_CALL_SETUP_TIMEOUT_MS` (default `7000`)
- `SBC_SIP_RINGING_ENABLED` (default `true`)
- `SBC_CALLSID_PREFIX` (default `rust`)
- `RUST_LOG` (default `info`)

## Twilio Routing Model

For inbound PSTN-to-Rust testing, route your Twilio phone number through **Elastic SIP Trunk Origination** to this SBC's public SIP endpoint (`udp/5060`).

- The Twilio Number's normal Voice webhook (TwiML) is not used for this inbound SIP path.
- The trunk Origination URI should target your SBC hostname/IP and UDP port 5060.
