"""Supported text extraction for RAG document ingestion."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

from fastapi import UploadFile
from pypdf import PdfReader

from app.services.rag.models import ExtractedSection


SUPPORTED_TEXT_MIME_TYPES = {"text/plain"}
SUPPORTED_PDF_MIME_TYPES = {"application/pdf"}


async def extract_sections(
    *,
    input_text: str | None,
    file: UploadFile | None,
    fallback_source: str | None,
) -> tuple[list[ExtractedSection], str]:
    """Extract text sections from pasted text or one supported upload."""
    normalized_input_text = normalize_text(input_text)
    if normalized_input_text:
        return (
            [ExtractedSection(text=normalized_input_text)],
            fallback_source or "pasted-text",
        )

    if file is None:
        raise ValueError("Provide either input_text or a text/PDF file.")

    file_name = file.filename or "uploaded-document"
    content_type = file.content_type or "application/octet-stream"
    file_bytes = await file.read()
    if not file_bytes:
        raise ValueError("Uploaded document was empty.")

    suffix = Path(file_name).suffix.lower()
    if content_type in SUPPORTED_TEXT_MIME_TYPES or suffix == ".txt":
        sections = [_extract_text_file(file_bytes)]
    elif content_type in SUPPORTED_PDF_MIME_TYPES or suffix == ".pdf":
        sections = _extract_pdf_sections(file_bytes)
    else:
        raise ValueError(
            "Only pasted text, .txt files, and extractable PDFs are supported."
        )

    return sections, fallback_source or file_name


def combine_sections(sections: list[ExtractedSection]) -> str:
    """Combine extracted sections into one text document for DB-native chunking."""
    document_parts = []
    for section in sections:
        if section.source_location:
            document_parts.append(f"{section.source_location}\n{section.text}")
        else:
            document_parts.append(section.text)
    return "\n\n".join(document_parts).strip()


def normalize_text(value: str | None) -> str | None:
    """Normalize whitespace in extracted text while preserving demo simplicity."""
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _extract_text_file(file_bytes: bytes) -> ExtractedSection:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Text files must be UTF-8 encoded.") from exc

    normalized = normalize_text(text)
    if normalized is None:
        raise ValueError("Text file did not contain extractable text.")
    return ExtractedSection(text=normalized)


def _extract_pdf_sections(file_bytes: bytes) -> list[ExtractedSection]:
    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError("PDF could not be opened.") from exc

    sections = []
    for index, page in enumerate(reader.pages, start=1):
        text = normalize_text(page.extract_text() or "")
        if text:
            sections.append(
                ExtractedSection(
                    text=text,
                    page_number=index,
                    source_location=f"page {index}",
                )
            )

    if not sections:
        raise ValueError("PDF did not contain extractable text. OCR is not supported.")
    return sections
