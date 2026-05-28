use std::env;
use std::net::{IpAddr, Ipv4Addr, SocketAddr, ToSocketAddrs};

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub control_bind: SocketAddr,
    pub ws_bind: SocketAddr,
    pub sip_bind: SocketAddr,
    pub local_sip_advertise_host: String,
    pub rtp_start_port: u16,
    pub rtp_end_port: u16,
    pub default_trunk_port: u16,
    pub backend_voice_ws_url: String,
    pub ws_connect_timeout_ms: u64,
    pub call_setup_timeout_ms: u64,
    pub sip_ringing_enabled: bool,
    pub callsid_prefix: String,
}

impl AppConfig {
    pub fn from_env() -> Self {
        let control_bind = socket_from_env("SBC_CONTROL_BIND", 8082);
        let ws_bind = socket_from_env("SBC_WS_BIND", 8083);
        let sip_bind = socket_from_env("SBC_SIP_BIND", 5060);
        let rtp_start_port = u16_from_env("SBC_RTP_START_PORT", 10000);
        let rtp_end_port = u16_from_env("SBC_RTP_END_PORT", 10100);
        let default_trunk_port = u16_from_env("SBC_TRUNK_PORT", 5060);
        let backend_voice_ws_url = string_from_env(
            "SBC_BACKEND_VOICE_WS_URL",
            "wss://demo.lebedev.ai/api/voice/stream",
        );
        let ws_connect_timeout_ms = u64_from_env("SBC_WS_CONNECT_TIMEOUT_MS", 3000);
        let call_setup_timeout_ms = u64_from_env("SBC_CALL_SETUP_TIMEOUT_MS", 7000);
        let sip_ringing_enabled = bool_from_env("SBC_SIP_RINGING_ENABLED", true);
        let callsid_prefix = string_from_env("SBC_CALLSID_PREFIX", "rust");
        let local_sip_advertise_host = env::var("SBC_ADVERTISE_HOST")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .and_then(|value| resolve_advertise_host(&value))
            .or_else(|| default_advertise_host_from_bind_ip(sip_bind.ip()))
            .unwrap_or_else(|| Ipv4Addr::LOCALHOST.to_string());

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
            backend_voice_ws_url,
            ws_connect_timeout_ms,
            call_setup_timeout_ms,
            sip_ringing_enabled,
            callsid_prefix,
        }
    }
}

fn resolve_advertise_host(value: &str) -> Option<String> {
    if let Ok(ip) = value.parse::<IpAddr>() {
        return Some(ip.to_string());
    }

    let mut first_any_ip: Option<String> = None;
    for addr in (value, 0).to_socket_addrs().ok()? {
        match addr.ip() {
            IpAddr::V4(v4) => return Some(v4.to_string()),
            ip => {
                if first_any_ip.is_none() {
                    first_any_ip = Some(ip.to_string());
                }
            }
        }
    }

    first_any_ip
}

fn default_advertise_host_from_bind_ip(bind_ip: IpAddr) -> Option<String> {
    if bind_ip.is_unspecified() {
        return None;
    }

    Some(bind_ip.to_string())
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

fn u64_from_env(key: &str, default_value: u64) -> u64 {
    env::var(key)
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(default_value)
}

fn bool_from_env(key: &str, default_value: bool) -> bool {
    env::var(key)
        .ok()
        .map(|value| value.trim().to_ascii_lowercase())
        .and_then(|value| match value.as_str() {
            "1" | "true" | "yes" | "y" | "on" => Some(true),
            "0" | "false" | "no" | "n" | "off" => Some(false),
            _ => None,
        })
        .unwrap_or(default_value)
}

fn string_from_env(key: &str, default_value: &str) -> String {
    env::var(key)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| default_value.to_string())
}

#[cfg(test)]
mod tests {
    use super::{default_advertise_host_from_bind_ip, resolve_advertise_host};
    use std::net::{IpAddr, Ipv4Addr};

    #[test]
    fn resolve_advertise_host_returns_ip_literal_as_is() {
        assert_eq!(
            resolve_advertise_host("129.80.152.84"),
            Some("129.80.152.84".to_string())
        );
    }

    #[test]
    fn resolve_advertise_host_resolves_hostname_to_ipv4() {
        assert_eq!(
            resolve_advertise_host("localhost"),
            Some("127.0.0.1".to_string())
        );
    }

    #[test]
    fn default_advertise_host_ignores_unspecified_bind_ip() {
        assert_eq!(
            default_advertise_host_from_bind_ip(IpAddr::V4(Ipv4Addr::UNSPECIFIED)),
            None
        );
    }
}
