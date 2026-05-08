use anyhow::{bail, Result};

use crate::models::{
    InputKind, InspectInputRequest, InspectInputResponse, NormalizeResponse, TextChunk,
};

pub fn normalize_text(value: &str) -> NormalizeResponse {
    let normalized = value.split_whitespace().collect::<Vec<_>>().join(" ");
    let output_bytes = normalized.len();
    let changed = normalized != value;
    NormalizeResponse {
        text: normalized,
        input_bytes: value.len(),
        output_bytes,
        changed,
    }
}

pub fn chunk_text(value: &str, chunk_size: usize, chunk_overlap: usize) -> Result<Vec<TextChunk>> {
    if chunk_size < 100 {
        bail!("chunk_size must be at least 100 characters");
    }
    if chunk_overlap >= chunk_size {
        bail!("chunk_overlap must be smaller than chunk_size");
    }

    let normalized = normalize_text(value).text;
    if normalized.is_empty() {
        return Ok(Vec::new());
    }
    if normalized.len() <= chunk_size {
        return Ok(vec![TextChunk {
            index: 0,
            bytes: normalized.len(),
            text: normalized,
        }]);
    }

    let mut chunks = Vec::new();
    let mut start = 0;
    while start < normalized.len() {
        let hard_end = next_boundary_at_or_before(&normalized, start + chunk_size);
        let end = find_split_point(&normalized, start, hard_end);
        let chunk = normalized[start..end].trim().to_owned();
        if !chunk.is_empty() {
            chunks.push(TextChunk {
                index: chunks.len(),
                bytes: chunk.len(),
                text: chunk,
            });
        }
        if end >= normalized.len() {
            break;
        }
        start = (end.saturating_sub(chunk_overlap)).max(start + 1);
        start = next_boundary_at_or_after(&normalized, start);
    }
    Ok(chunks)
}

pub fn inspect_input(input: &InspectInputRequest) -> InspectInputResponse {
    if input.size_bytes == 0 {
        return InspectInputResponse {
            accepted: false,
            kind: InputKind::Empty,
            reason: Some("Uploaded document was empty.".to_owned()),
        };
    }

    let suffix = input
        .file_name
        .rsplit_once('.')
        .map(|(_, suffix)| suffix.to_ascii_lowercase())
        .unwrap_or_default();
    let content_type = input.content_type.to_ascii_lowercase();

    if content_type == "text/plain" || suffix == "txt" {
        return InspectInputResponse {
            accepted: true,
            kind: InputKind::Text,
            reason: None,
        };
    }
    if content_type == "application/pdf" || suffix == "pdf" {
        return InspectInputResponse {
            accepted: true,
            kind: InputKind::Pdf,
            reason: None,
        };
    }
    if content_type.starts_with("image/") {
        return rejected(InputKind::Image, "Images are outside the demo input scope.");
    }
    if content_type.starts_with("audio/") {
        return rejected(InputKind::Audio, "Audio is outside the demo input scope.");
    }
    if content_type.starts_with("video/") {
        return rejected(InputKind::Video, "Video is outside the demo input scope.");
    }
    rejected(
        InputKind::Unsupported,
        "Only pasted text, plain text files, and extractable PDFs are supported.",
    )
}

fn rejected(kind: InputKind, reason: &str) -> InspectInputResponse {
    InspectInputResponse {
        accepted: false,
        kind,
        reason: Some(reason.to_owned()),
    }
}

fn find_split_point(value: &str, start: usize, hard_end: usize) -> usize {
    if hard_end >= value.len() {
        return value.len();
    }

    let window = &value[start..hard_end];
    let minimum = window.len() / 2;
    for pattern in ["\n\n", "\n", ". ", " "] {
        if let Some(index) = window.rfind(pattern) {
            if index >= minimum {
                return start + index + pattern.len();
            }
        }
    }
    hard_end
}

fn next_boundary_at_or_before(value: &str, index: usize) -> usize {
    let mut index = index.min(value.len());
    while index > 0 && !value.is_char_boundary(index) {
        index -= 1;
    }
    index
}

fn next_boundary_at_or_after(value: &str, index: usize) -> usize {
    let mut index = index.min(value.len());
    while index < value.len() && !value.is_char_boundary(index) {
        index += 1;
    }
    index
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_whitespace() {
        let result = normalize_text("  hello   world\n\nagain ");
        assert_eq!(result.text, "hello world again");
        assert!(result.changed);
    }

    #[test]
    fn chunks_with_overlap() {
        let text = format!("{} {}", "a".repeat(120), "b".repeat(120));
        let chunks = chunk_text(&text, 150, 20).unwrap();
        assert!(chunks.len() >= 2);
        assert_eq!(chunks[0].index, 0);
    }

    #[test]
    fn rejects_tiny_chunk_size() {
        assert!(chunk_text("hello", 50, 0).is_err());
    }

    #[test]
    fn accepts_plain_text() {
        let result = inspect_input(&InspectInputRequest {
            file_name: "notes.txt".to_owned(),
            content_type: "text/plain".to_owned(),
            size_bytes: 10,
        });
        assert!(result.accepted);
        assert_eq!(result.kind, InputKind::Text);
    }

    #[test]
    fn rejects_image() {
        let result = inspect_input(&InspectInputRequest {
            file_name: "photo.png".to_owned(),
            content_type: "image/png".to_owned(),
            size_bytes: 10,
        });
        assert!(!result.accepted);
        assert_eq!(result.kind, InputKind::Image);
    }
}
