mod models;
mod routes;
mod text;

use std::env;
use std::net::{IpAddr, SocketAddr};

use anyhow::Context;
use axum::Router;
use tokio::net::TcpListener;
use tower_http::trace::TraceLayer;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing();
    let addr = listen_addr()?;
    let app = app();
    let listener = TcpListener::bind(addr)
        .await
        .with_context(|| format!("failed to bind {addr}"))?;

    info!(%addr, "demo-text-tools listening");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .context("server exited unexpectedly")
}

fn app() -> Router {
    routes::router().layer(TraceLayer::new_for_http())
}

fn listen_addr() -> anyhow::Result<SocketAddr> {
    let host = env::var("TEXT_TOOLS_HOST").unwrap_or_else(|_| "127.0.0.1".to_owned());
    let port = env::var("TEXT_TOOLS_PORT").unwrap_or_else(|_| "8081".to_owned());
    listen_addr_from(&host, &port)
}

fn listen_addr_from(host: &str, port: &str) -> anyhow::Result<SocketAddr> {
    let port = port
        .parse::<u16>()
        .context("TEXT_TOOLS_PORT must be a valid TCP port")?;
    let ip = host
        .parse::<IpAddr>()
        .with_context(|| format!("TEXT_TOOLS_HOST must be an IP address, got {host}"))?;
    Ok(SocketAddr::new(ip, port))
}

fn init_tracing() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::fmt().with_env_filter(filter).init();
}

async fn shutdown_signal() {
    if let Err(err) = tokio::signal::ctrl_c().await {
        tracing::warn!(%err, "failed to install Ctrl+C handler");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::Ipv4Addr;

    #[test]
    fn default_listen_addr_is_localhost_8081() {
        assert_eq!(
            listen_addr_from("127.0.0.1", "8081").unwrap(),
            SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 8081)
        );
    }
}
