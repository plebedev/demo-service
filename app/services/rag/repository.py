"""Shared relational persistence helpers for RAG documents and labels."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rag import RagDocument, RagDocumentChunk, RagLabel, RagPersonaDocument
from app.services.rag.extraction import combine_sections, extract_sections
from app.services.rag.models import ExtractedSection, PreparedRagDocument


class RagDocumentRepository:
    """Common document and label persistence used by all RAG strategies."""

    async def prepare_document(
        self,
        *,
        input_text: str | None,
        file: UploadFile | None,
        source: str | None,
        title: str | None,
    ) -> PreparedRagDocument:
        """Extract text and compute a stable content hash before persistence."""
        sections, resolved_source = await extract_sections(
            input_text=input_text,
            file=file,
            fallback_source=source,
        )
        combined_text = combine_sections(sections)
        if not combined_text:
            raise ValueError("No extractable text was available for RAG ingestion.")
        return PreparedRagDocument(
            source=resolved_source,
            title=title,
            content_sha256=self.content_hash(sections),
            sections=sections,
            combined_text=combined_text,
        )

    def create_document(
        self,
        session: Session,
        *,
        source: str,
        labels: list[str],
        title: str | None = None,
        content_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RagDocument:
        """Create one document and assign normalized labels."""
        normalized_labels = self.normalize_labels(labels)
        if not normalized_labels:
            raise ValueError("At least one RAG label is required.")

        document = RagDocument(
            source=source,
            title=title,
            content_sha256=content_sha256,
            metadata_serialized=self.serialize_json(metadata),
        )
        document.labels = [
            self._get_or_create_label(session, label_key)
            for label_key in normalized_labels
        ]
        session.add(document)
        session.flush()
        return document

    def get_document_by_hash(
        self,
        session: Session,
        content_sha256: str,
    ) -> RagDocument | None:
        """Return a previously ingested document by content hash."""
        return session.scalar(
            select(RagDocument).where(RagDocument.content_sha256 == content_sha256)
        )

    def link_persona_document(
        self,
        session: Session,
        *,
        persona_id: int,
        document: RagDocument,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RagPersonaDocument:
        """Link a reusable document to a persona, idempotently."""
        existing = session.get(
            RagPersonaDocument,
            {"persona_id": persona_id, "document_id": document.id},
        )
        if existing is not None:
            return existing

        link = RagPersonaDocument(
            persona_id=persona_id,
            document_id=document.id,
            display_name=display_name,
            source=document.source,
            metadata_serialized=self.serialize_json(metadata),
        )
        session.add(link)
        session.flush()
        return link

    def unlink_persona_document(
        self,
        session: Session,
        *,
        persona_id: int,
        document_id: int,
    ) -> bool:
        """Remove a persona-document link without deleting chunks."""
        link = session.get(
            RagPersonaDocument,
            {"persona_id": persona_id, "document_id": document_id},
        )
        if link is None:
            return False
        session.delete(link)
        session.flush()
        return True

    def document_chunk_count(self, session: Session, document_id: int) -> int:
        """Return the persisted chunk count for one document."""
        return (
            session.query(RagDocumentChunk)
            .filter(RagDocumentChunk.document_id == document_id)
            .count()
        )

    def normalize_labels(self, labels: list[str]) -> list[str]:
        """Normalize, dedupe, and preserve order for RAG label keys."""
        normalized = []
        seen = set()
        for label in labels:
            label_key = label.strip().lower()
            if label_key and label_key not in seen:
                normalized.append(label_key)
                seen.add(label_key)
        return normalized

    def serialize_json(self, value: dict[str, Any] | None) -> str | None:
        """Serialize structured metadata into Oracle-compatible text storage."""
        if value is None:
            return None
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    def content_hash(self, sections: list[ExtractedSection]) -> str:
        """Hash extracted content and source locations for dedupe."""
        payload = [
            {
                "text": section.text,
                "page_number": section.page_number,
                "source_location": section.source_location,
            }
            for section in sections
        ]
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def oracle_model_name(self, model_name: str) -> str:
        """Validate a model object name before embedding it into Oracle SQL."""
        normalized = model_name.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", normalized):
            raise ValueError("Oracle embedding model name is invalid.")
        return normalized

    def _get_or_create_label(self, session: Session, label_key: str) -> RagLabel:
        label = session.scalar(select(RagLabel).where(RagLabel.label_key == label_key))
        if label is not None:
            return label

        label = RagLabel(label_key=label_key)
        session.add(label)
        session.flush()
        return label
