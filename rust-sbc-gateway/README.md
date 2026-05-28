# rust-sbc-gateway

Infrastructure-only SIP/RTP SBC/B2BUA experiment service for warm transfer prototyping.

## Scope (Phase 1)

- UDP SIP signaling engine on port `5060`
- RTP sender support on configurable UDP range (default `10000-10100`)
- WebSocket ingest endpoint (`/api/voice/stream`) that parses Twilio-style media frames
- Central in-memory call session state registry
- Internal control API to create sessions, update state, and start transfer attempts
- Prometheus-compatible metrics endpoint (`/metrics`)

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
- `RUST_LOG` (default `info`)
