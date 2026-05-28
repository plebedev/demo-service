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
}

pub fn build_sip_invite(request: &SipInviteRequest) -> anyhow::Result<SipInvite> {
    let target_addr = format!("{}:{}", request.trunk_host, request.trunk_port);
    let call_id = format!("{}@rust-sbc-node", Uuid::new_v4());
    let branch = format!("z9hG4bK{}", Uuid::new_v4().simple());
    let from_tag = Uuid::new_v4().simple().to_string();

    let mut sdp = String::new();
    sdp.push_str("v=0\r\n");
    sdp.push_str(&format!(
        "o=RustSBC 2890844526 2890844526 IN IP4 {}\r\n",
        request.local_host
    ));
    sdp.push_str("s=-\r\n");
    sdp.push_str(&format!("c=IN IP4 {}\r\n", request.local_host));
    sdp.push_str("t=0 0\r\n");
    sdp.push_str(&format!("m=audio {} RTP/AVP 0\r\n", request.local_rtp_port));
    sdp.push_str("a=rtpmap:0 PCMU/8000\r\n");

    let mut headers = String::new();
    headers.push_str(&format!(
        "INVITE sip:{}@{} SIP/2.0\r\n",
        request.target_phone, request.trunk_host
    ));
    headers.push_str(&format!(
        "Via: SIP/2.0/UDP {}:5060;branch={}\r\n",
        request.local_host, branch
    ));
    headers.push_str(&format!(
        "To: <sip:{}@{}>\r\n",
        request.target_phone, request.trunk_host
    ));
    headers.push_str(&format!(
        "From: <sip:{}@{}>;tag={}\r\n",
        request.twilio_number, request.trunk_host, from_tag
    ));
    headers.push_str(&format!("Call-ID: {}\r\n", call_id));
    headers.push_str("CSeq: 1 INVITE\r\n");
    headers.push_str(&format!(
        "Contact: <sip:{}@{}:5060>\r\n",
        request.twilio_number, request.local_host
    ));
    headers.push_str("Content-Type: application/sdp\r\n");
    headers.push_str("Max-Forwards: 70\r\n");
    headers.push_str(&format!("X-Session-ID: {}\r\n", request.session_id));
    headers.push_str(&format!("Content-Length: {}\r\n\r\n", sdp.len()));

    Ok(SipInvite {
        call_id,
        payload: format!("{}{}", headers, sdp),
        target_addr,
    })
}

pub fn is_sip_200_ok(message: &str) -> bool {
    parse_sip_status_line(message)
        .map(|status| status.starts_with("SIP/2.0 200"))
        .unwrap_or(false)
}

pub fn parse_sip_status_line(message: &str) -> Option<String> {
    message.lines().next().map(|line| line.trim().to_string())
}

pub fn extract_audio_port_from_sdp(message: &str) -> Option<u16> {
    for line in message.lines() {
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

#[cfg(test)]
mod tests {
    use super::{
        build_sip_invite, extract_audio_port_from_sdp, is_sip_200_ok, parse_sip_status_line,
        SipInviteRequest,
    };

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
        assert!(invite.payload.contains("m=audio 10000 RTP/AVP 0"));

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
    }
}
