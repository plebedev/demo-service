use std::collections::HashMap;
use std::net::{IpAddr, SocketAddr, ToSocketAddrs};

use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct SipInviteRequest {
    pub session_id: String,
    pub target_phone: String,
    pub twilio_number: String,
    pub trunk_host: String,
    pub trunk_port: u16,
    pub local_host: String,
    pub local_rtp_port: u16,
}

#[derive(Debug, Clone)]
pub struct SipInvite {
    pub call_id: String,
    pub payload: String,
    pub target_addr: String,
    pub request_uri: String,
    pub from: String,
    pub cseq: u32,
}

#[derive(Debug, Clone)]
pub struct SipParsedRequest {
    pub method: String,
    pub request_uri: String,
    pub version: String,
    pub headers: SipHeaders,
    pub body: String,
}

#[derive(Debug, Clone)]
pub struct SipParsedResponse {
    pub version: String,
    pub status_code: u16,
    pub reason_phrase: String,
    pub headers: SipHeaders,
    pub body: String,
}

#[derive(Debug, Clone, Default)]
pub struct SipHeaders {
    entries: Vec<(String, String)>,
    first_values: HashMap<String, String>,
}

impl SipHeaders {
    pub fn get(&self, name: &str) -> Option<&String> {
        self.first_values.get(&name.trim().to_ascii_lowercase())
    }

    pub fn values<'a>(&'a self, name: &str) -> impl Iterator<Item = &'a str> {
        let normalized_name = name.trim().to_ascii_lowercase();
        self.entries
            .iter()
            .filter(move |(entry_name, _)| *entry_name == normalized_name)
            .map(|(_, value)| value.as_str())
    }

    fn insert(&mut self, name: String, value: String) {
        self.entries.push((name.clone(), value.clone()));
        self.first_values.entry(name).or_insert(value);
    }
}

#[derive(Debug, Clone)]
pub struct InboundDialogSignaling {
    pub call_id: String,
    pub local_from: String,
    pub remote_to: String,
    pub remote_request_uri: String,
    pub local_host: String,
    pub local_cseq: u32,
}

#[derive(Debug, Clone)]
pub struct SipDatagram {
    pub payload: String,
    pub target_addr: SocketAddr,
}

pub fn build_sip_invite(request: &SipInviteRequest) -> anyhow::Result<SipInvite> {
    let target_addr = format!("{}:{}", request.trunk_host, request.trunk_port);
    let call_id = format!("{}@rust-sbc-node", Uuid::new_v4());
    let branch = format!("z9hG4bK{}", Uuid::new_v4().simple());
    let from_tag = Uuid::new_v4().simple().to_string();
    let request_uri = format!("sip:{}@{}", request.target_phone, request.trunk_host);
    let from = format!(
        "<sip:{}@{}>;tag={}",
        request.twilio_number, request.trunk_host, from_tag
    );
    let to = format!("<sip:{}@{}>", request.target_phone, request.trunk_host);
    let contact = format!(
        "<sip:{}@{}:5060>",
        request.twilio_number, request.local_host
    );
    let cseq = 1u32;

    let sdp = build_sdp_offer(&request.local_host, request.local_rtp_port);
    let mut lines = vec![
        format!("INVITE {} SIP/2.0", request_uri),
        format!(
            "Via: SIP/2.0/UDP {}:5060;branch={}",
            request.local_host, branch
        ),
        format!("To: {}", to),
        format!("From: {}", from),
        format!("Call-ID: {}", call_id),
        format!("CSeq: {} INVITE", cseq),
        format!("Contact: {}", contact),
        "Content-Type: application/sdp".to_string(),
        "Max-Forwards: 70".to_string(),
        format!("X-Session-ID: {}", request.session_id),
        format!("Content-Length: {}", sdp.len()),
    ];

    Ok(SipInvite {
        call_id,
        payload: build_sip_message(&mut lines, Some(&sdp)),
        target_addr,
        request_uri,
        from,
        cseq,
    })
}

pub fn build_sip_trying_for_invite(request: &SipParsedRequest) -> Option<String> {
    build_response_for_request(request, 100, "Trying", None, None)
}

pub fn build_sip_ringing_for_invite(request: &SipParsedRequest, local_tag: &str) -> Option<String> {
    build_response_for_request(request, 180, "Ringing", Some(local_tag), None)
}

pub fn build_sip_200_ok_for_invite(
    request: &SipParsedRequest,
    local_tag: &str,
    local_host: &str,
    local_rtp_port: u16,
) -> Option<String> {
    let sdp = build_sdp_offer(local_host, local_rtp_port);
    let from = request.headers.get("from")?;
    let to = request.headers.get("to")?;
    let call_id = request.headers.get("call-id")?;
    let cseq = request.headers.get("cseq")?;
    let to_value = if to.to_ascii_lowercase().contains(";tag=") {
        to.to_string()
    } else {
        format!("{};tag={}", to, local_tag)
    };
    let contact = format!("<sip:sbc@{}:5060>", local_host);

    let mut lines = vec![
        "SIP/2.0 200 OK".to_string(),
        format!("From: {}", from),
        format!("To: {}", to_value),
        format!("Call-ID: {}", call_id),
        format!("CSeq: {}", cseq),
        format!("Contact: {}", contact),
        "Content-Type: application/sdp".to_string(),
        format!("Content-Length: {}", sdp.len()),
    ];

    prepend_response_route_headers(request, &mut lines)?;

    Some(build_sip_message(&mut lines, Some(&sdp)))
}

pub fn build_sip_final_response_for_invite(
    request: &SipParsedRequest,
    status_code: u16,
    reason_phrase: &str,
    local_tag: &str,
) -> Option<String> {
    build_response_for_request(request, status_code, reason_phrase, Some(local_tag), None)
}

pub fn build_response_for_in_dialog_request(
    request: &str,
    status_code: u16,
    reason_phrase: &str,
) -> Option<String> {
    let parsed = parse_sip_request(request)?;
    build_response_for_request(&parsed, status_code, reason_phrase, None, None)
}

pub fn build_ack_for_final_response(
    response: &str,
    invite: &SipInvite,
    source_addr: SocketAddr,
    local_host: &str,
) -> Option<SipDatagram> {
    let parsed = parse_sip_response(response)?;
    let call_id = parsed.headers.get("call-id")?;
    if call_id != &invite.call_id {
        return None;
    }
    let to = parsed.headers.get("to")?;
    let target_uri = parsed
        .headers
        .get("contact")
        .and_then(|contact| extract_uri_from_name_addr(contact))
        .unwrap_or_else(|| invite.request_uri.clone());
    let target_addr = parsed
        .headers
        .get("contact")
        .and_then(|contact| parse_socket_addr_from_sip_uri(contact, source_addr.port()))
        .unwrap_or(source_addr);
    let branch = format!("z9hG4bK{}", Uuid::new_v4().simple());

    let mut lines = vec![
        format!("ACK {} SIP/2.0", target_uri),
        format!("Via: SIP/2.0/UDP {}:5060;branch={}", local_host, branch),
        format!("To: {}", to),
        format!("From: {}", invite.from),
        format!("Call-ID: {}", invite.call_id),
        format!("CSeq: {} ACK", invite.cseq),
        "Max-Forwards: 70".to_string(),
        "Content-Length: 0".to_string(),
    ];

    Some(SipDatagram {
        payload: build_sip_message(&mut lines, None),
        target_addr,
    })
}

pub fn build_bye_request(dialog: &InboundDialogSignaling) -> String {
    let branch = format!("z9hG4bK{}", Uuid::new_v4().simple());
    let cseq = dialog.local_cseq.saturating_add(1);
    let mut lines = vec![
        format!("BYE {} SIP/2.0", dialog.remote_request_uri),
        format!(
            "Via: SIP/2.0/UDP {}:5060;branch={}",
            dialog.local_host, branch
        ),
        format!("From: {}", dialog.local_from),
        format!("To: {}", dialog.remote_to),
        format!("Call-ID: {}", dialog.call_id),
        format!("CSeq: {} BYE", cseq),
        "Max-Forwards: 70".to_string(),
        "Content-Length: 0".to_string(),
    ];
    build_sip_message(&mut lines, None)
}

pub fn parse_sip_request(message: &str) -> Option<SipParsedRequest> {
    let (head, body) = split_sip_message(message);
    let mut lines = head.lines();
    let request_line = lines.next()?.trim().to_string();
    let mut request_parts = request_line.split_whitespace();
    let method = request_parts.next()?.to_ascii_uppercase();
    let request_uri = request_parts.next()?.to_string();
    let version = request_parts.next()?.to_string();
    if !version.eq_ignore_ascii_case("SIP/2.0") {
        return None;
    }

    Some(SipParsedRequest {
        method,
        request_uri,
        version,
        headers: parse_headers(lines),
        body: body.to_string(),
    })
}

pub fn parse_sip_response(message: &str) -> Option<SipParsedResponse> {
    let (head, body) = split_sip_message(message);
    let mut lines = head.lines();
    let status_line = lines.next()?.trim().to_string();
    let mut parts = status_line.split_whitespace();
    let version = parts.next()?.to_string();
    if !version.eq_ignore_ascii_case("SIP/2.0") {
        return None;
    }
    let status_code = parts.next()?.parse::<u16>().ok()?;
    let reason_phrase = parts.collect::<Vec<_>>().join(" ");
    Some(SipParsedResponse {
        version,
        status_code,
        reason_phrase,
        headers: parse_headers(lines),
        body: body.to_string(),
    })
}

pub fn parse_sip_request_method(message: &str) -> Option<String> {
    parse_sip_request(message).map(|req| req.method)
}

pub fn parse_sip_status_code(message: &str) -> Option<u16> {
    parse_sip_response(message).map(|resp| resp.status_code)
}

pub fn parse_sip_status_line(message: &str) -> Option<String> {
    message.lines().next().map(|line| line.trim().to_string())
}

pub fn sip_header_value(message: &str, header_name: &str) -> Option<String> {
    if let Some(request) = parse_sip_request(message) {
        return request.headers.get(header_name).cloned();
    }
    if let Some(response) = parse_sip_response(message) {
        return response.headers.get(header_name).cloned();
    }
    None
}

pub fn extract_audio_port_from_sdp(message: &str) -> Option<u16> {
    let body = if let Some(request) = parse_sip_request(message) {
        request.body
    } else {
        parse_sip_response(message)?.body
    };

    for line in body.lines() {
        let trimmed = line.trim();
        if !trimmed.starts_with("m=audio") {
            continue;
        }
        let mut parts = trimmed.split_whitespace();
        let _ = parts.next();
        let port = parts.next()?.parse::<u16>().ok()?;
        return Some(port);
    }
    None
}

pub fn extract_media_addr_from_sdp(message: &str, fallback_host: IpAddr) -> Option<SocketAddr> {
    let body = if let Some(request) = parse_sip_request(message) {
        request.body
    } else {
        parse_sip_response(message)?.body
    };
    let mut host = fallback_host;
    let mut port: Option<u16> = None;
    for line in body.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("c=IN") {
            let parts = trimmed.split_whitespace().collect::<Vec<_>>();
            if parts.len() >= 3 {
                host = parts[2].parse::<IpAddr>().ok()?;
            }
        } else if trimmed.starts_with("m=audio") {
            let mut parts = trimmed.split_whitespace();
            let _ = parts.next();
            port = parts.next().and_then(|p| p.parse::<u16>().ok());
        }
    }
    Some(SocketAddr::new(host, port?))
}

pub fn response_destination_from_via(via_header: &str, fallback: SocketAddr) -> Option<SocketAddr> {
    let mut received: Option<IpAddr> = None;
    let mut rport: Option<u16> = None;

    let mut segments = via_header.split(';');
    let sent_by_segment = segments.next()?.trim();
    for segment in segments {
        let trimmed = segment.trim();
        if let Some((k, v)) = trimmed.split_once('=') {
            if k.eq_ignore_ascii_case("received") {
                received = v.parse::<IpAddr>().ok();
            } else if k.eq_ignore_ascii_case("rport") {
                rport = v.parse::<u16>().ok();
            }
        }
    }

    let sent_by = sent_by_segment
        .split_whitespace()
        .last()
        .unwrap_or_default();
    let sent_by_parts = parse_host_port_without_resolution(sent_by);

    let host = if let Some(ip) = received {
        ip
    } else if let Some((host_part, _)) = &sent_by_parts {
        if let Ok(ip) = host_part.parse::<IpAddr>() {
            ip
        } else {
            resolve_host_ip(host_part).unwrap_or(fallback.ip())
        }
    } else {
        fallback.ip()
    };

    let port = rport
        .or_else(|| sent_by_parts.as_ref().map(|(_, port)| *port))
        .unwrap_or(fallback.port());

    Some(SocketAddr::new(host, port))
}

fn parse_host_port_without_resolution(value: &str) -> Option<(String, u16)> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }

    if let Some((host, port)) = trimmed.rsplit_once(':') {
        let parsed_port = port.parse::<u16>().ok()?;
        return Some((host.to_string(), parsed_port));
    }

    Some((trimmed.to_string(), 5060))
}

fn resolve_host_ip(host: &str) -> Option<IpAddr> {
    if let Ok(ip) = host.parse::<IpAddr>() {
        return Some(ip);
    }

    let mut addrs = format!("{}:{}", host, 5060).to_socket_addrs().ok()?;
    addrs.next().map(|addr| addr.ip())
}

pub fn is_sip_200_ok(message: &str) -> bool {
    parse_sip_response(message)
        .map(|resp| resp.status_code == 200)
        .unwrap_or(false)
}

fn parse_headers<'a>(lines: impl Iterator<Item = &'a str>) -> SipHeaders {
    let mut headers = SipHeaders::default();
    for line in lines {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            break;
        }
        let Some((name, value)) = trimmed.split_once(':') else {
            continue;
        };
        headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_string());
    }
    headers
}

fn split_sip_message(message: &str) -> (&str, &str) {
    if let Some((head, body)) = message.split_once("\r\n\r\n") {
        (head, body)
    } else if let Some((head, body)) = message.split_once("\n\n") {
        (head, body)
    } else {
        (message, "")
    }
}

fn build_response_for_request(
    request: &SipParsedRequest,
    status_code: u16,
    reason_phrase: &str,
    local_tag: Option<&str>,
    body: Option<&str>,
) -> Option<String> {
    let from = request.headers.get("from")?;
    let to = request.headers.get("to")?;
    let call_id = request.headers.get("call-id")?;
    let cseq = request.headers.get("cseq")?;
    let to_value = if to.to_ascii_lowercase().contains(";tag=") {
        to.to_string()
    } else if let Some(tag) = local_tag {
        format!("{};tag={}", to, tag)
    } else {
        to.to_string()
    };
    let mut lines = vec![
        format!("SIP/2.0 {} {}", status_code, reason_phrase),
        format!("From: {}", from),
        format!("To: {}", to_value),
        format!("Call-ID: {}", call_id),
        format!("CSeq: {}", cseq),
    ];

    prepend_response_route_headers(request, &mut lines)?;

    if let Some(body_value) = body {
        lines.push("Content-Type: application/sdp".to_string());
        lines.push(format!("Content-Length: {}", body_value.len()));
        Some(build_sip_message(&mut lines, Some(body_value)))
    } else {
        lines.push("Content-Length: 0".to_string());
        Some(build_sip_message(&mut lines, None))
    }
}

fn prepend_response_route_headers(
    request: &SipParsedRequest,
    lines: &mut Vec<String>,
) -> Option<()> {
    let vias = request.headers.values("via").collect::<Vec<_>>();
    if vias.is_empty() {
        return None;
    }

    let mut prefix_lines = Vec::new();
    for via in vias {
        prefix_lines.push(format!("Via: {}", via));
    }
    for record_route in request.headers.values("record-route") {
        prefix_lines.push(format!("Record-Route: {}", record_route));
    }

    lines.splice(1..1, prefix_lines);
    Some(())
}

fn build_sdp_offer(local_host: &str, local_rtp_port: u16) -> String {
    let addr_type = if local_host.contains(':') {
        "IP6"
    } else {
        "IP4"
    };
    let lines = [
        "v=0".to_string(),
        format!(
            "o=RustSBC 2890844526 2890844526 IN {} {}",
            addr_type, local_host
        ),
        "s=-".to_string(),
        format!("c=IN {} {}", addr_type, local_host),
        "t=0 0".to_string(),
        format!("m=audio {} RTP/AVP 0 8 101", local_rtp_port),
        "a=rtpmap:0 PCMU/8000".to_string(),
        "a=rtpmap:8 PCMA/8000".to_string(),
        "a=rtpmap:101 telephone-event/8000".to_string(),
        "a=fmtp:101 0-16".to_string(),
        "a=ptime:20".to_string(),
        "a=sendrecv".to_string(),
    ];
    lines.join("\r\n") + "\r\n"
}

fn build_sip_message(lines: &mut [String], body: Option<&str>) -> String {
    let mut payload = String::new();
    for line in lines {
        payload.push_str(line);
        payload.push_str("\r\n");
    }
    payload.push_str("\r\n");
    if let Some(body) = body {
        payload.push_str(body);
    }
    payload
}

pub fn extract_uri_from_name_addr(value: &str) -> Option<String> {
    if let (Some(start), Some(end)) = (value.find('<'), value.find('>')) {
        return Some(value[start + 1..end].trim().to_string());
    }
    Some(value.trim().to_string())
}

fn parse_socket_addr_from_sip_uri(value: &str, default_port: u16) -> Option<SocketAddr> {
    let uri = extract_uri_from_name_addr(value)?;
    let without_prefix = uri.strip_prefix("sip:").unwrap_or(&uri);
    let host_port = if let Some((_, hostpart)) = without_prefix.rsplit_once('@') {
        hostpart
    } else {
        without_prefix
    };
    let host_port = host_port.split(';').next().unwrap_or(host_port);
    parse_host_port(host_port, default_port)
}

fn parse_host_port(host_port: &str, default_port: u16) -> Option<SocketAddr> {
    if let Ok(addr) = host_port.parse::<SocketAddr>() {
        return Some(addr);
    }
    if let Ok(ip) = host_port.parse::<IpAddr>() {
        return Some(SocketAddr::new(ip, default_port));
    }
    let mut addrs = format!("{}:{}", host_port, default_port)
        .to_socket_addrs()
        .ok()?;
    addrs.next()
}

#[cfg(test)]
mod tests {
    use super::{
        build_ack_for_final_response, build_response_for_in_dialog_request,
        build_sip_200_ok_for_invite, build_sip_invite, extract_audio_port_from_sdp,
        extract_media_addr_from_sdp, is_sip_200_ok, parse_sip_request, parse_sip_request_method,
        parse_sip_status_code, parse_sip_status_line, response_destination_from_via,
        sip_header_value, SipInviteRequest,
    };
    use std::net::{IpAddr, Ipv4Addr, SocketAddr};

    #[test]
    fn invite_has_required_sections_and_correct_content_length() {
        let request = SipInviteRequest {
            session_id: "session-1".to_string(),
            target_phone: "+15551231234".to_string(),
            twilio_number: "+15557654321".to_string(),
            trunk_host: "example.sip.twilio.com".to_string(),
            trunk_port: 5060,
            local_host: "10.0.0.5".to_string(),
            local_rtp_port: 10000,
        };

        let invite = build_sip_invite(&request).expect("invite should build");
        assert!(invite
            .payload
            .starts_with("INVITE sip:+15551231234@example.sip.twilio.com SIP/2.0"));
        assert!(invite.payload.contains("Content-Type: application/sdp"));
        assert!(invite.payload.contains("m=audio 10000 RTP/AVP 0 8 101"));
        assert!(invite.payload.contains("\r\n\r\nv=0\r\n"));

        let split = invite.payload.split("\r\n\r\n").collect::<Vec<_>>();
        assert_eq!(split.len(), 2);
        let headers = split[0];
        let sdp = split[1];
        let content_length_line = headers
            .lines()
            .find(|line| line.starts_with("Content-Length:"))
            .expect("content length header");
        let content_length: usize = content_length_line
            .split(':')
            .nth(1)
            .expect("content length value")
            .trim()
            .parse()
            .expect("content length should parse");
        assert_eq!(content_length, sdp.len());
    }

    #[test]
    fn parses_200_ok_and_sdp_audio_port() {
        let response =
            "SIP/2.0 200 OK\r\nVia: SIP/2.0/UDP example\r\n\r\nv=0\r\nm=audio 18452 RTP/AVP 0\r\n";
        assert!(is_sip_200_ok(response));
        assert_eq!(
            parse_sip_status_line(response),
            Some("SIP/2.0 200 OK".to_string())
        );
        assert_eq!(extract_audio_port_from_sdp(response), Some(18452));
        assert_eq!(parse_sip_status_code(response), Some(200));
    }

    #[test]
    fn parses_case_insensitive_sip_headers() {
        let response =
            "SIP/2.0 603 Decline\r\ncall-id: abc@host\r\ntO: <sip:+1555@example.com>;tag=z\r\n\r\n";
        assert_eq!(
            sip_header_value(response, "Call-ID"),
            Some("abc@host".to_string())
        );
        assert_eq!(
            sip_header_value(response, "to"),
            Some("<sip:+1555@example.com>;tag=z".to_string())
        );
    }

    #[test]
    fn builds_ack_for_final_response_and_uses_contact_target() {
        let request = SipInviteRequest {
            session_id: "session-1".to_string(),
            target_phone: "+15551231234".to_string(),
            twilio_number: "+15557654321".to_string(),
            trunk_host: "example.pstn.twilio.com".to_string(),
            trunk_port: 5060,
            local_host: "129.80.152.84".to_string(),
            local_rtp_port: 10000,
        };
        let invite = build_sip_invite(&request).expect("invite should build");
        let response = format!(
            "SIP/2.0 200 OK\r\nCall-ID: {}\r\nTo: <sip:+15551231234@example.pstn.twilio.com>;tag=abc123\r\nContact: <sip:54.172.60.3:5060>\r\n\r\n",
            invite.call_id
        );
        let source = SocketAddr::from(([10, 0, 0, 1], 5060));

        let ack = build_ack_for_final_response(&response, &invite, source, "129.80.152.84")
            .expect("ack should build");
        assert!(ack.payload.starts_with("ACK sip:54.172.60.3:5060 SIP/2.0"));
        assert!(ack.payload.contains("CSeq: 1 ACK"));
        assert_eq!(ack.target_addr, SocketAddr::from(([54, 172, 60, 3], 5060)));
    }

    #[test]
    fn parses_request_method() {
        let bye = "BYE sip:+17817346618@129.80.152.84:5060 SIP/2.0\r\nCall-ID: a\r\n\r\n";
        assert_eq!(parse_sip_request_method(bye), Some("BYE".to_string()));
        let response = "SIP/2.0 200 OK\r\nCall-ID: a\r\n\r\n";
        assert_eq!(parse_sip_request_method(response), None);
    }

    #[test]
    fn builds_200_ok_for_bye_request_without_folding() {
        let bye_request = "BYE sip:+17817346618@129.80.152.84:5060 SIP/2.0\r\n\
                           Via: SIP/2.0/UDP 54.172.60.3:5060;branch=z9hG4bKabc\r\n\
                           From: <sip:+16177100171@peter-voice-demo.pstn.ashburn.twilio.com>;tag=fromtag\r\n\
                           To: <sip:+17817346618@peter-voice-demo.pstn.ashburn.twilio.com>;tag=totag\r\n\
                           Call-ID: call-123\r\n\
                           CSeq: 1 BYE\r\n\r\n";

        let response =
            build_response_for_in_dialog_request(bye_request, 200, "OK").expect("response builds");
        assert!(response.starts_with("SIP/2.0 200 OK\r\n"));
        assert!(response.contains("\r\nCSeq: 1 BYE\r\n"));
        assert!(!response.contains("\r\n "));
    }

    #[test]
    fn builds_200_ok_for_invite_with_to_tag() {
        let invite = "INVITE sip:demo@example.com SIP/2.0\r\n\
                      Via: SIP/2.0/UDP 1.2.3.4:5060;branch=z9\r\n\
                      Via: SIP/2.0/UDP 5.6.7.8:5060;branch=z10\r\n\
                      Record-Route: <sip:proxy-a.example.com;lr>\r\n\
                      From: <sip:a@b>;tag=abc\r\n\
                      To: <sip:demo@example.com>\r\n\
                      Call-ID: id-1\r\n\
                      CSeq: 1 INVITE\r\n\r\n";
        let parsed = parse_sip_request(invite).expect("should parse");
        let response = build_sip_200_ok_for_invite(&parsed, "localtag", "129.80.152.84", 10000)
            .expect("response");
        assert!(response.contains("Via: SIP/2.0/UDP 1.2.3.4:5060;branch=z9\r\nVia: SIP/2.0/UDP 5.6.7.8:5060;branch=z10\r\n"));
        assert!(response.contains("Record-Route: <sip:proxy-a.example.com;lr>"));
        assert!(response.contains("To: <sip:demo@example.com>;tag=localtag"));
        assert!(response.contains("Contact: <sip:sbc@129.80.152.84:5060>"));
        assert!(response.contains("m=audio 10000 RTP/AVP 0 8 101"));
    }

    #[test]
    fn sip_header_value_keeps_top_via_when_multiple_present() {
        let invite = "INVITE sip:demo@example.com SIP/2.0\r\n\
                      Via: SIP/2.0/UDP 54.172.60.2:5060;branch=z9hG4bK-top\r\n\
                      Via: SIP/2.0/UDP 172.16.1.10:5060;branch=z9hG4bK-lower\r\n\
                      Call-ID: id-2\r\n\
                      CSeq: 1 INVITE\r\n\r\n";

        assert_eq!(
            sip_header_value(invite, "Via"),
            Some("SIP/2.0/UDP 54.172.60.2:5060;branch=z9hG4bK-top".to_string())
        );
    }

    #[test]
    fn extracts_media_socket_from_sdp() {
        let msg = "SIP/2.0 200 OK\r\nCall-ID: id\r\n\r\nv=0\r\nc=IN IP4 54.1.2.3\r\nm=audio 18000 RTP/AVP 0\r\n";
        let addr =
            extract_media_addr_from_sdp(msg, IpAddr::V4(Ipv4Addr::LOCALHOST)).expect("media addr");
        assert_eq!(addr, SocketAddr::from(([54, 1, 2, 3], 18000)));
    }

    #[test]
    fn computes_via_response_destination_with_received_rport() {
        let via = "SIP/2.0/UDP host.example.com:5060;branch=z9;rport=34567;received=129.80.152.84";
        let fallback = SocketAddr::from(([10, 0, 0, 2], 5060));
        let destination =
            response_destination_from_via(via, fallback).expect("destination should resolve");
        assert_eq!(destination, SocketAddr::from(([129, 80, 152, 84], 34567)));
    }
}
