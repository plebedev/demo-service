FROM rust:1.95-slim AS builder

WORKDIR /app

COPY text-tools/Cargo.toml text-tools/Cargo.lock* ./
COPY text-tools/src ./src

RUN cargo build --release

FROM debian:bookworm-slim AS runtime

ENV TEXT_TOOLS_HOST=0.0.0.0 \
    TEXT_TOOLS_PORT=8081 \
    RUST_LOG=info

WORKDIR /app
COPY --from=builder /app/target/release/demo-text-tools /usr/local/bin/demo-text-tools

EXPOSE 8081

CMD ["demo-text-tools"]
