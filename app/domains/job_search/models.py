"""Shared helpers and constants for the Job Search domain pack."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.core.context_engine.models import ArtifactChunk, SourceLink

DOMAIN_ID = "job_search"

ARTIFACT_TYPE_IDS = [
    "job_description",
    "resume",
    "recruiter_message",
    "interview_notes",
    "company_research",
    "personal_story",
    "compensation_notes",
    "follow_up_notes",
]


@dataclass(frozen=True)
class ExtractedValue:
    """One extracted value and its provenance."""

    value: str
    source_link: SourceLink


def normalize_space(value: str) -> str:
    """Collapse whitespace for stable extracted labels."""
    return re.sub(r"\s+", " ", value).strip(" -:\t\n\r")


def first_source_link(chunks: list[ArtifactChunk]) -> SourceLink:
    """Return a broad fallback source link for an artifact."""
    if chunks:
        return chunks[0].source_link
    raise ValueError("At least one chunk is required for extraction.")


def source_for_match(
    chunks: list[ArtifactChunk],
    match_text: str,
    *,
    label: str | None = None,
) -> SourceLink:
    """Return a source link for a matched excerpt."""
    needle = match_text.strip()
    for chunk in chunks:
        offset = chunk.text.lower().find(needle.lower())
        if offset >= 0:
            start = chunk.start_offset + offset
            end = start + len(needle)
            return SourceLink(
                artifact_id=chunk.artifact_id,
                chunk_id=chunk.id,
                start_offset=start,
                end_offset=end,
                label=label,
                excerpt=needle[:500],
            )
    fallback = first_source_link(chunks)
    return fallback.model_copy(
        update={
            "label": label or fallback.label,
            "excerpt": needle[:500] or fallback.excerpt,
        }
    )


def lines_containing(
    chunks: list[ArtifactChunk],
    patterns: Iterable[str],
    *,
    label: str,
) -> list[ExtractedValue]:
    """Return unique source-linked lines that match any regex pattern."""
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    values: list[ExtractedValue] = []
    seen: set[str] = set()
    for chunk in chunks:
        for line in chunk.text.splitlines():
            cleaned = normalize_space(line)
            if not cleaned or cleaned.lower() in seen:
                continue
            if any(pattern.search(cleaned) for pattern in compiled):
                seen.add(cleaned.lower())
                values.append(
                    ExtractedValue(
                        value=cleaned,
                        source_link=source_for_match(
                            chunks,
                            cleaned,
                            label=label,
                        ),
                    )
                )
    return values


def keyword_values(
    chunks: list[ArtifactChunk],
    keywords: Iterable[str],
    *,
    label: str,
) -> list[ExtractedValue]:
    """Return source-linked keyword mentions found in artifact chunks."""
    values: list[ExtractedValue] = []
    seen: set[str] = set()
    for keyword in keywords:
        pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
        for chunk in chunks:
            match = pattern.search(chunk.text)
            if match is None or keyword.lower() in seen:
                continue
            seen.add(keyword.lower())
            values.append(
                ExtractedValue(
                    value=keyword,
                    source_link=SourceLink(
                        artifact_id=chunk.artifact_id,
                        chunk_id=chunk.id,
                        start_offset=chunk.start_offset + match.start(),
                        end_offset=chunk.start_offset + match.end(),
                        label=label,
                        excerpt=chunk.text[match.start() : match.end()],
                    ),
                )
            )
            break
    return values
