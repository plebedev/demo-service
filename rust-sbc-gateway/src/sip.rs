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
    pub via: String,
    pub from: String,
    pub cseq: u32,
}

pub fn build_sip_invite(request: &SipInviteRequest) -> anyhow::Result<SipInvite> {
    let target_addr = format!("{}:{}", request.trunk_host, request.trunk_port);
    let call_id = format!("{}@rust-sbc-node", Uuid::new_v4());
    let branch = format!("z9hG4bK{}", Uuid::new_v4().simple());
    let from_tag = Uuid::new_v4().simple().to_string();

    let addr_type = if request.local_host.contains(':') {
        "IP6"
    } else {
        "IP4"
    };

    let mut sdp = String::new();
    sdp.push_str("v=0\r\n");
    sdp.push_str(&format!(
        "o=RustSBC 2890844526 2890844526 IN {} {}\r\n",
        addr_type, request.local_host
    ));
    sdp.push_str("s=-\r\n");
    sdp.push_str(&format!("c=IN {} {}\r\n", addr_type, request.local_host));
    sdp.push_str("t=0 0\r\n");
    sdp.push_str(&format!(
        "m=audio {} RTP/AVP 0 8 101\r\n",
        request.local_rtp_port
    ));
    sdp.push_str("a=rtpmap:0 PCMU/8000\r\n");
    sdp.push_str("a=rtpmap:8 PCMA/8000\r\n");
    sdp.push_str("a=rtpmap:101 telephone-event/8000\r\n");
    sdp.push_str("a=fmtp:101 0-16\r\n");
    sdp.push_str("a=ptime:20\r\n");
    sdp.push_str("a=sendrecv\r\n");

    let request_uri = format!("sip:{}@{}", request.target_phone, request.trunk_host);
    let via = format!("SIP/2.0/UDP {}:5060;branch={}", request.local_host, branch);
    let from = format!(
        "<sip:{}@{}>;tag={}",
        request.twilio_number, request.trunk_host, from_tag
    );
    let cseq = 1u32;

    let mut headers = String::new();
    headers.push_str(&format!("INVITE {} SIP/2.0\r\n", request_uri));
    headers.push_str(&format!("Via: {}\r\n", via));
    headers.push_str(&format!(
        "To: <sip:{}@{}>\r\n",
        request.target_phone, request.trunk_host
    ));
    headers.push_str(&format!("From: {}\r\n", from));
    headers.push_str(&format!("Call-ID: {}\r\n", call_id));
    headers.push_str(&format!("CSeq: {} INVITE\r\n", cseq));
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
        request_uri,
        via,
        from,
        cseq,
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

pub fn parse_sip_request_method(message: &str) -> Option<String> {
    let line = parse_sip_status_line(message)?;
    if line.starts_with("SIP/2.0") {
        return None;
    }
    let mut parts = line.split_whitespace();
    let method = parts.next()?;
    let _uri = parts.next()?;
    let version = parts.next()?;
    if version.eq_ignore_ascii_case("SIP/2.0") {
        return Some(method.to_ascii_uppercase());
    }
    None
}

pub fn parse_sip_status_code(message: &str) -> Option<u16> {
    let status_line = parse_sip_status_line(message)?;
    let mut parts = status_line.split_whitespace();
    let protocol = parts.next()?;
    if !protocol.eq_ignore_ascii_case("SIP/2.0") {
        return None;
    }
    parts.next()?.parse::<u16>().ok()
}

pub fn sip_header_value(message: &str, header_name: &str) -> Option<String> {
    let needle = header_name.to_ascii_lowercase();
    for line in message.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            break;
        }
        let Some((name, value)) = trimmed.split_once(':') else {
            continue;
        };
        if name.trim().eq_ignore_ascii_case(&needle) {
            return Some(value.trim().to_string());
        }
    }
    None
}

pub fn build_response_for_in_dialog_request(
    request: &str,
    status_code: u16,
    reason_phrase: &str,
) -> Option<String> {
    let via = sip_header_value(request, "Via")?;
    let from = sip_header_value(request, "From")?;
    let to = sip_header_value(request, "To")?;
    let call_id = sip_header_value(request, "Call-ID")?;
    let cseq = sip_header_value(request, "CSeq")?;

    Some(format!(
        "SIP/2.0 {} {}\r\n\
        Via: {}\r\n\
        From: {}\r\n\
        To: {}\r\n\
        Call-ID: {}\r\n\
        CSeq: {}\r\n\
        Content-Length: 0\r\n\r\n",
        status_code, reason_phrase, via, from, to, call_id, cseq
    ))
}

pub fn build_ack_for_final_response(response: &str, invite: &SipInvite) -> Option<String> {
    let to = sip_header_value(response, "To")?;
    let call_id = sip_header_value(response, "Call-ID")?;
    if call_id != invite.call_id {
        return None;
    }

    Some(format!(
        "ACK {} SIP/2.0\r\n\
        Via: {}\r\n\
        To: {}\r\n\
        From: {}\r\n\
        Call-ID: {}\r\n\
        CSeq: {} ACK\r\n\
        Max-Forwards: 70\r\n\
        Content-Length: 0\r\n\r\n",
        invite.request_uri, invite.via, to, invite.from, invite.call_id, invite.cseq
    ))
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
        build_ack_for_final_response, build_response_for_in_dialog_request, build_sip_invite,
        extract_audio_port_from_sdp, is_sip_200_ok, parse_sip_request_method,
        parse_sip_status_code, parse_sip_status_line, sip_header_value, SipInviteRequest,
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
        assert!(invite.payload.contains("m=audio 10000 RTP/AVP 0 8 101"));
        assert!(invite.payload.contains("a=rtpmap:8 PCMA/8000"));
        assert!(invite.payload.contains("a=rtpmap:101 telephone-event/8000"));

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
    fn builds_ack_for_final_response() {
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
            "SIP/2.0 603 Decline\r\nCall-ID: {}\r\nTo: <sip:+15551231234@example.pstn.twilio.com>;tag=abc123\r\n\r\n",
            invite.call_id
        );

        let ack = build_ack_for_final_response(&response, &invite).expect("ack should build");
        assert!(ack.starts_with("ACK sip:+15551231234@example.pstn.twilio.com SIP/2.0"));
        assert!(ack.contains("CSeq: 1 ACK"));
        assert!(ack.contains("Content-Length: 0"));
    }

    #[test]
    fn parses_request_method() {
        let bye = "BYE sip:+17817346618@129.80.152.84:5060 SIP/2.0\r\nCall-ID: a\r\n\r\n";
        assert_eq!(parse_sip_request_method(bye), Some("BYE".to_string()));
        let response = "SIP/2.0 200 OK\r\nCall-ID: a\r\n\r\n";
        assert_eq!(parse_sip_request_method(response), None);
    }

    #[test]
    fn builds_200_ok_for_bye_request() {
        let bye_request = "BYE sip:+17817346618@129.80.152.84:5060 SIP/2.0\r\n\
                           Via: SIP/2.0/UDP 54.172.60.3:5060;branch=z9hG4bKabc\r\n\
                           From: <sip:+16177100171@peter-voice-demo.pstn.ashburn.twilio.com>;tag=fromtag\r\n\
                           To: <sip:+17817346618@peter-voice-demo.pstn.ashburn.twilio.com>;tag=totag\r\n\
                           Call-ID: call-123\r\n\
                           CSeq: 1 BYE\r\n\r\n";

        let response =
            build_response_for_in_dialog_request(bye_request, 200, "OK").expect("response builds");
        assert!(response.starts_with("SIP/2.0 200 OK"));
        assert!(response.contains("CSeq: 1 BYE"));
        assert!(response.contains("Call-ID: call-123"));
        assert!(response.contains("Content-Length: 0"));
    }
}
