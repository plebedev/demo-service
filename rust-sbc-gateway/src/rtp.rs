#[derive(Debug, Clone)]
pub struct RtpPacketBuilder {
    sequence: u16,
    timestamp: u32,
    ssrc: u32,
}

impl RtpPacketBuilder {
    pub fn new(start_sequence: u16, start_timestamp: u32, ssrc: u32) -> Self {
        Self {
            sequence: start_sequence,
            timestamp: start_timestamp,
            ssrc,
        }
    }

    pub fn build_packet(&mut self, payload: &[u8]) -> Vec<u8> {
        let mut packet = Vec::with_capacity(12 + payload.len());

        // Byte 0: RTP version 2 (0x80), no padding, no extensions, no CSRC.
        packet.push(0x80);
        // Byte 1: Payload type 0 = PCMU / G.711 μ-law.
        packet.push(0x00);

        packet.extend_from_slice(&self.sequence.to_be_bytes());
        packet.extend_from_slice(&self.timestamp.to_be_bytes());
        packet.extend_from_slice(&self.ssrc.to_be_bytes());
        packet.extend_from_slice(payload);

        self.sequence = self.sequence.wrapping_add(1);
        // 20ms chunks at 8kHz => 160 samples per RTP packet.
        self.timestamp = self.timestamp.wrapping_add(160);

        packet
    }
}

#[cfg(test)]
mod tests {
    use super::RtpPacketBuilder;

    #[test]
    fn builds_expected_header_and_increments() {
        let mut builder = RtpPacketBuilder::new(10, 320, 0x1122_3344);
        let payload = [1u8, 2, 3, 4];

        let first = builder.build_packet(&payload);
        let second = builder.build_packet(&payload);

        assert_eq!(first[0], 0x80);
        assert_eq!(first[1], 0x00);
        assert_eq!(u16::from_be_bytes([first[2], first[3]]), 10);
        assert_eq!(
            u32::from_be_bytes([first[4], first[5], first[6], first[7]]),
            320
        );
        assert_eq!(
            u32::from_be_bytes([first[8], first[9], first[10], first[11]]),
            0x1122_3344
        );
        assert_eq!(&first[12..], payload);

        assert_eq!(u16::from_be_bytes([second[2], second[3]]), 11);
        assert_eq!(
            u32::from_be_bytes([second[4], second[5], second[6], second[7]]),
            480
        );
    }
}
