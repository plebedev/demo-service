use anyhow::{bail, Result};

use crate::models::{
    AnalyzeLimits, AnalyzeRequest, AnalyzeResponse, InputKind, InspectInputRequest,
    InspectInputResponse, NormalizeResponse, TextChunk, TextStats,
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

pub fn analyze_text(request: &AnalyzeRequest) -> Result<AnalyzeResponse> {
    if request.limits.max_bytes == 0 {
        bail!("max_bytes must be greater than zero");
    }

    let normalized = normalize_text(&request.text);
    let (bounded_text, trimmed) = trim_to_utf8_boundary(&normalized.text, request.limits.max_bytes);
    let chunks = chunk_text(
        &bounded_text,
        request.limits.max_chunk_size,
        request.limits.chunk_overlap,
    )?;
    let warnings = analyze_warnings(&bounded_text, &chunks, &request.limits, trimmed);
    let stats = text_stats(&request.text, &bounded_text, &chunks);

    let normalized_bytes = bounded_text.len();
    Ok(AnalyzeResponse {
        normalized_text: bounded_text,
        input_bytes: normalized.input_bytes,
        normalized_bytes,
        trimmed,
        chunks,
        stats,
        warnings,
    })
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

fn trim_to_utf8_boundary(value: &str, max_bytes: usize) -> (String, bool) {
    if value.len() <= max_bytes {
        return (value.to_owned(), false);
    }
    let mut end = max_bytes;
    while end > 0 && !value.is_char_boundary(end) {
        end -= 1;
    }
    (value[..end].trim_end().to_owned(), true)
}

fn analyze_warnings(
    text: &str,
    chunks: &[TextChunk],
    limits: &AnalyzeLimits,
    trimmed: bool,
) -> Vec<String> {
    let mut warnings = Vec::new();
    if trimmed {
        warnings.push("Text was trimmed to fit the configured byte budget.".to_owned());
    }
    if text.is_empty() {
        warnings.push("No meaningful text remained after normalization.".to_owned());
    }
    if chunks.is_empty() && !text.is_empty() {
        warnings.push("Text did not produce any chunks.".to_owned());
    }
    if has_long_unbroken_token(text, limits.max_chunk_size) {
        warnings.push(
            "Text contains a long unbroken section that may produce rough chunk boundaries."
                .to_owned(),
        );
    }
    warnings
}

fn text_stats(original_text: &str, analyzed_text: &str, chunks: &[TextChunk]) -> TextStats {
    let (min_chunk_bytes, max_chunk_bytes, total_chunk_bytes) = chunks
        .iter()
        .map(|c| c.bytes)
        .fold((usize::MAX, 0, 0), |(min, max, total), b| {
            (min.min(b), max.max(b), total + b)
        });
    // then fix up min when chunks is empty
    let (min_chunk_bytes, max_chunk_bytes) = if chunks.is_empty() {
        (0, 0)
    } else {
        (min_chunk_bytes, max_chunk_bytes)
    };

    let chunk_count = chunks.len();
    let avg_chunk_bytes = total_chunk_bytes.checked_div(chunk_count).unwrap_or(0);

    TextStats {
        character_count: analyzed_text.chars().count(),
        line_count: count_lines(original_text),
        paragraph_count: count_paragraphs(original_text),
        url_count: count_urls(analyzed_text),
        email_count: count_emails(analyzed_text),
        phone_like_count: count_phone_like(analyzed_text),
        chunk_count,
        min_chunk_bytes,
        max_chunk_bytes,
        avg_chunk_bytes,
    }
}

fn count_lines(text: &str) -> usize {
    text.lines().count()
}

fn count_paragraphs(text: &str) -> usize {
    text.split("\n\n")
        .filter(|paragraph| !paragraph.trim().is_empty())
        .count()
}

fn count_urls(text: &str) -> usize {
    text.split_whitespace()
        .filter(|token| {
            let token = token.trim_matches(|character: char| {
                character.is_ascii_punctuation() && character != '/' && character != ':'
            });
            token.starts_with("http://") || token.starts_with("https://")
        })
        .count()
}

fn count_emails(text: &str) -> usize {
    text.split_whitespace()
        .filter(|token| {
            let token = token.trim_matches(|character: char| {
                character.is_ascii_punctuation() && character != '@' && character != '.'
            });
            let Some((local, domain)) = token.split_once('@') else {
                return false;
            };
            !local.is_empty()
                && domain.contains('.')
                && !domain.starts_with('.')
                && !domain.ends_with('.')
        })
        .count()
}

fn count_phone_like(text: &str) -> usize {
    text.split_whitespace()
        .filter(|token| {
            let digit_count = token
                .chars()
                .filter(|character| character.is_ascii_digit())
                .count();
            digit_count >= 10
        })
        .count()
}

fn has_long_unbroken_token(text: &str, chunk_size: usize) -> bool {
    let threshold = chunk_size.max(100);
    text.split_whitespace().any(|token| token.len() > threshold) // .len() = byte length
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
    fn analyzes_text_with_stats_chunks_and_signals() {
        let result = analyze_text(&AnalyzeRequest {
            text: " Hello   https://example.test\nperson@example.test\nCall 415-555-1212 "
                .to_owned(),
            limits: AnalyzeLimits {
                max_bytes: 500,
                max_chunk_size: 100,
                chunk_overlap: 10,
            },
        })
        .unwrap();

        assert_eq!(
            result.normalized_text,
            "Hello https://example.test person@example.test Call 415-555-1212"
        );
        assert!(!result.trimmed);
        assert_eq!(result.stats.url_count, 1);
        assert_eq!(result.stats.email_count, 1);
        assert_eq!(result.stats.phone_like_count, 1);
        assert_eq!(result.stats.chunk_count, result.chunks.len());
        assert!(result.warnings.is_empty());
    }

    #[test]
    fn analyzes_text_with_utf8_safe_trimming() {
        let result = analyze_text(&AnalyzeRequest {
            text: "alpha ééé omega".to_owned(),
            limits: AnalyzeLimits {
                max_bytes: 9,
                max_chunk_size: 100,
                chunk_overlap: 0,
            },
        })
        .unwrap();

        assert!(result.trimmed);
        assert!(result
            .normalized_text
            .is_char_boundary(result.normalized_text.len()));
        assert!(result
            .warnings
            .contains(&"Text was trimmed to fit the configured byte budget.".to_owned()));
    }

    #[test]
    fn analyze_rejects_zero_byte_budget() {
        let error = analyze_text(&AnalyzeRequest {
            text: "alpha".to_owned(),
            limits: AnalyzeLimits {
                max_bytes: 0,
                max_chunk_size: 100,
                chunk_overlap: 0,
            },
        })
        .unwrap_err();

        assert!(error.to_string().contains("max_bytes"));
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
