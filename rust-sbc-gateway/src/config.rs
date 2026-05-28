use std::env;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub control_bind: SocketAddr,
    pub ws_bind: SocketAddr,
    pub sip_bind: SocketAddr,
    pub local_sip_advertise_host: String,
    pub rtp_start_port: u16,
    pub rtp_end_port: u16,
    pub default_trunk_port: u16,
}

impl AppConfig {
    pub fn from_env() -> Self {
        let control_bind = socket_from_env("SBC_CONTROL_BIND", 8082);
        let ws_bind = socket_from_env("SBC_WS_BIND", 8083);
        let sip_bind = socket_from_env("SBC_SIP_BIND", 5060);
        let rtp_start_port = u16_from_env("SBC_RTP_START_PORT", 10000);
        let rtp_end_port = u16_from_env("SBC_RTP_END_PORT", 10100);
        let default_trunk_port = u16_from_env("SBC_TRUNK_PORT", 5060);
        let local_sip_advertise_host = env::var("SBC_ADVERTISE_HOST")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| sip_bind.ip().to_string());

        let (rtp_start_port, rtp_end_port) = if rtp_start_port <= rtp_end_port {
            (rtp_start_port, rtp_end_port)
        } else {
            (rtp_end_port, rtp_start_port)
        };

        Self {
            control_bind,
            ws_bind,
            sip_bind,
            local_sip_advertise_host,
            rtp_start_port,
            rtp_end_port,
            default_trunk_port,
        }
    }
}

fn socket_from_env(key: &str, default_port: u16) -> SocketAddr {
    let default = SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), default_port);
    env::var(key)
        .ok()
        .and_then(|value| value.parse::<SocketAddr>().ok())
        .unwrap_or(default)
}

fn u16_from_env(key: &str, default_value: u16) -> u16 {
    env::var(key)
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(default_value)
}
