"""Deterministic phase-1 input ingestion for persisted demo runs."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable

from fastapi import UploadFile
from pypdf import PdfReader

from app.core.config import Settings
from app.schemas.runs import (
    AcceptedRunFileSummary,
    RejectedRunFile,
    RunIngestionCounts,
    RunIngestionLimits,
    RunIngestionSummary,
    RunInputMetadata,
    UploadedRunFile,
)

SUPPORTED_TEXT_MIME_TYPES = {"text/plain"}
SUPPORTED_PDF_MIME_TYPES = {"application/pdf"}


class IngestionResult:
    """Normalized ingestion payload persisted onto a run."""

    def __init__(
        self,
        *,
        raw_pasted_text: str | None,
        normalized_input_text: str | None,
        input_metadata_json: RunInputMetadata,
        uploaded_files_json: list[UploadedRunFile],
        ingestion_summary_json: RunIngestionSummary,
    ) -> None:
        self.raw_pasted_text = raw_pasted_text
        self.normalized_input_text = normalized_input_text
        self.input_metadata_json = input_metadata_json
        self.uploaded_files_json = uploaded_files_json
        self.ingestion_summary_json = ingestion_summary_json


async def ingest_run_input(
    *,
    settings: Settings,
    pasted_text: str | None,
    files: list[UploadFile],
) -> IngestionResult:
    """Normalize pasted text and uploaded files with deterministic limits."""
    warnings: list[str] = []
    accepted_files: list[UploadedRunFile] = []
    rejected_files: list[RejectedRunFile] = []
    total_extracted_bytes = 0

    normalized_pasted_text = _normalize_text(pasted_text)
    raw_pasted_bytes = _utf8_len(normalized_pasted_text or "")
    stored_pasted_text = normalized_pasted_text

    if raw_pasted_bytes > settings.max_pasted_text_bytes and normalized_pasted_text:
        stored_pasted_text, pasted_trimmed = _trim_text_to_bytes(
            normalized_pasted_text, settings.max_pasted_text_bytes
        )
        if pasted_trimmed:
            warnings.append(
                "The pasted notes were longer than this demo brain allows, so I kept the first slice."
            )

    for index, upload in enumerate(files):
        if index >= settings.max_files_per_run:
            rejected_files.append(
                RejectedRunFile(
                    file_name=upload.filename or "untitled",
                    content_type=upload.content_type or "application/octet-stream",
                    reason="Too many files. I kept the first few and left the rest at the velvet rope.",
                )
            )
            continue

        file_name = upload.filename or "untitled"
        content_type = upload.content_type or "application/octet-stream"
        file_bytes = await upload.read()
        file_size_bytes = len(file_bytes)

        if file_size_bytes == 0:
            rejected_files.append(
                RejectedRunFile(
                    file_name=file_name,
                    content_type=content_type,
                    reason="That file arrived empty, which is very minimalist even for this demo.",
                )
            )
            continue

        if file_size_bytes > settings.max_file_size_bytes:
            rejected_files.append(
                RejectedRunFile(
                    file_name=file_name,
                    content_type=content_type,
                    reason="That file is over the size limit, so I rejected it before pretending to be heroic.",
                )
            )
            continue

        extractor = _resolve_extractor(file_name, content_type)
        if extractor is None:
            rejected_files.append(
                RejectedRunFile(
                    file_name=file_name,
                    content_type=content_type,
                    reason=_unsupported_reason(content_type),
                )
            )
            continue

        extracted_text, extraction_warning = extractor(file_bytes)
        normalized_extracted_text = _normalize_text(extracted_text)

        if extraction_warning:
            rejected_files.append(
                RejectedRunFile(
                    file_name=file_name,
                    content_type=content_type,
                    reason=extraction_warning,
                )
            )
            continue

        if not normalized_extracted_text:
            rejected_files.append(
                RejectedRunFile(
                    file_name=file_name,
                    content_type=content_type,
                    reason="I could open that file, but there was no extractable text to keep.",
                )
            )
            continue

        remaining_extracted_budget = max(
            settings.max_extracted_text_bytes - total_extracted_bytes, 0
        )
        if remaining_extracted_budget == 0:
            rejected_files.append(
                RejectedRunFile(
                    file_name=file_name,
                    content_type=content_type,
                    reason="The file-text budget was already full, so this one never made it onto the tiny demo desk.",
                )
            )
            continue

        kept_text, trimmed = _trim_text_to_bytes(
            normalized_extracted_text, remaining_extracted_budget
        )
        if not kept_text:
            rejected_files.append(
                RejectedRunFile(
                    file_name=file_name,
                    content_type=content_type,
                    reason="There was no remaining text budget for that file after earlier uploads.",
                )
            )
            continue

        kept_bytes = _utf8_len(kept_text)
        total_extracted_bytes += kept_bytes

        file_record = UploadedRunFile(
            file_name=file_name,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            extracted_text=kept_text,
            extracted_text_bytes=kept_bytes,
            trimmed=trimmed,
        )
        accepted_files.append(file_record)

        if file_record.trimmed:
            warnings.append(
                f"{file_name} was longer than the file-text budget, so I kept the first extractable slice."
            )

    normalized_input_text, workflow_trimmed = _build_workflow_input_text(
        pasted_text=stored_pasted_text,
        accepted_files=accepted_files,
        max_total_bytes=settings.max_total_workflow_text_bytes,
    )
    if workflow_trimmed:
        warnings.append(
            "This is a demo, not a memory palace. I kept a representative slice so I could stay coherent."
        )

    source_kind = "mixed_input"
    if stored_pasted_text and not accepted_files:
        source_kind = "pasted_text"
    elif accepted_files and not stored_pasted_text:
        source_kind = "file_upload"

    return IngestionResult(
        raw_pasted_text=stored_pasted_text,
        normalized_input_text=normalized_input_text,
        input_metadata_json=RunInputMetadata(
            source_kind=source_kind,
            accepted_file_count=len(accepted_files),
            rejected_file_count=len(rejected_files),
            warning_count=len(warnings),
        ),
        uploaded_files_json=accepted_files,
        ingestion_summary_json=RunIngestionSummary(
            warnings=warnings,
            counts=RunIngestionCounts(
                accepted_files=len(accepted_files),
                rejected_files=len(rejected_files),
                trimmed_files=sum(1 for item in accepted_files if item.trimmed),
                accepted_pasted_text=1 if stored_pasted_text else 0,
                trimmed_pasted_text=(
                    1
                    if normalized_pasted_text
                    and stored_pasted_text != normalized_pasted_text
                    else 0
                ),
            ),
            accepted_files=[
                AcceptedRunFileSummary(
                    file_name=item.file_name,
                    content_type=item.content_type,
                    file_size_bytes=item.file_size_bytes,
                    extracted_text_bytes=item.extracted_text_bytes,
                    trimmed=item.trimmed,
                )
                for item in accepted_files
            ],
            rejected_files=rejected_files,
            limits=RunIngestionLimits(
                max_files_per_run=settings.max_files_per_run,
                max_file_size_bytes=settings.max_file_size_bytes,
                max_extracted_text_bytes=settings.max_extracted_text_bytes,
                max_total_workflow_text_bytes=settings.max_total_workflow_text_bytes,
                max_pasted_text_bytes=settings.max_pasted_text_bytes,
                strategy="Keep pasted text as entered, then accept files in upload order. Trim by taking the first bytes that fit each configured budget.",
            ),
            workflow_text_bytes=_utf8_len(normalized_input_text or ""),
        ),
    )


def _build_workflow_input_text(
    *,
    pasted_text: str | None,
    accepted_files: list[UploadedRunFile],
    max_total_bytes: int,
) -> tuple[str | None, bool]:
    sections: list[str] = []
    if pasted_text:
        sections.append("Pasted notes:\n" + pasted_text)

    for item in accepted_files:
        sections.append(f"File: {item.file_name}\n{item.extracted_text}")

    if not sections:
        return None, False

    combined = "\n\n".join(sections)
    return _trim_text_to_bytes(combined, max_total_bytes)


def _resolve_extractor(
    file_name: str, content_type: str
) -> Callable[[bytes], tuple[str | None, str | None]] | None:
    suffix = Path(file_name).suffix.lower()
    if content_type in SUPPORTED_TEXT_MIME_TYPES or suffix == ".txt":
        return _extract_text_file
    if content_type in SUPPORTED_PDF_MIME_TYPES or suffix == ".pdf":
        return _extract_pdf_text
    return None


def _extract_text_file(file_bytes: bytes) -> tuple[str | None, str | None]:
    try:
        return file_bytes.decode("utf-8"), None
    except UnicodeDecodeError:
        return (
            None,
            "That file is not plain UTF-8 text, and this milestone is staying boring on purpose.",
        )


def _extract_pdf_text(file_bytes: bytes) -> tuple[str | None, str | None]:
    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception:
        return (
            None,
            "That PDF would not open cleanly, so I rejected it instead of making up OCR powers.",
        )

    page_text = [page.extract_text() or "" for page in reader.pages]
    combined = "\n".join(text.strip() for text in page_text if text.strip())

    if not combined:
        return (
            None,
            "That PDF looks image-only or otherwise non-extractable. This demo only reads selectable PDF text.",
        )
    return combined, None


def _unsupported_reason(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "Images are out for phase 1. No OCR cape, no secret vision model."
    if content_type.startswith("audio/") or content_type.startswith("video/"):
        return "Audio and video are not supported here. This demo still prefers documents that sit still."
    return "That file type is outside the phase-1 demo menu. Plain text and text-based PDFs only."


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _trim_text_to_bytes(value: str, max_bytes: int) -> tuple[str | None, bool]:
    if max_bytes <= 0:
        return None, bool(value)

    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False

    trimmed = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    return (trimmed or None), True


def _utf8_len(value: str) -> int:
    return len(value.encode("utf-8"))
