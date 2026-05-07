"""Shared relational persistence helpers for RAG documents and labels."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rag import RagDocument, RagLabel


class RagDocumentRepository:
    """Common document and label persistence used by all RAG strategies."""

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
