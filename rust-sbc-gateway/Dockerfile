FROM rust:1.95-slim AS builder

WORKDIR /app

COPY rust-sbc-gateway/Cargo.toml rust-sbc-gateway/Cargo.lock* ./
COPY rust-sbc-gateway/src ./src

RUN cargo build --release

FROM debian:bookworm-slim AS runtime

ENV SBC_CONTROL_BIND=0.0.0.0:8082 \
    SBC_WS_BIND=0.0.0.0:8083 \
    SBC_SIP_BIND=0.0.0.0:5060 \
    SBC_RTP_START_PORT=10000 \
    SBC_RTP_END_PORT=10100 \
    SBC_TRUNK_PORT=5060 \
    RUST_LOG=info

WORKDIR /app
COPY --from=builder /app/target/release/rust-sbc-gateway /usr/local/bin/rust-sbc-gateway

EXPOSE 8082 8083 5060/udp

CMD ["rust-sbc-gateway"]
