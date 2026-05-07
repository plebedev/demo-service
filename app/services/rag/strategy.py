"""RAG strategy interfaces and shared service facade."""

from __future__ import annotations

from typing import Protocol

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.rag.models import (
    PreparedRagDocument,
    RagDocumentResult,
    RagSearchResult,
)


class RagStrategy(Protocol):
    """Environment-specific RAG implementation contract."""

    async def ingest_document(
        self,
        session: Session,
        *,
        settings: Settings,
        labels: list[str],
        source: str | None,
        title: str | None,
        input_text: str | None,
        file: UploadFile | None,
    ) -> RagDocumentResult:
        """Ingest one supported document and persist searchable chunks."""

    def create_document_from_prepared(
        self,
        session: Session,
        *,
        settings: Settings,
        prepared: PreparedRagDocument,
        labels: list[str],
    ) -> RagDocumentResult:
        """Persist and embed an already extracted document."""

    def search(
        self,
        session: Session,
        *,
        settings: Settings,
        labels: list[str],
        query: str,
        limit: int,
    ) -> list[RagSearchResult]:
        """Search chunks within the requested labels."""


class RagService:
    """Use-case facade for protected RAG APIs."""

    def __init__(self, strategy: RagStrategy) -> None:
        self.strategy = strategy

    async def ingest_document(
        self,
        session: Session,
        *,
        settings: Settings,
        labels: list[str],
        source: str | None,
        title: str | None,
        input_text: str | None,
        file: UploadFile | None,
    ) -> RagDocumentResult:
        """Ingest one supported document with the bound RAG strategy."""
        return await self.strategy.ingest_document(
            session,
            settings=settings,
            labels=labels,
            source=source,
            title=title,
            input_text=input_text,
            file=file,
        )

    def create_document_from_prepared(
        self,
        session: Session,
        *,
        settings: Settings,
        prepared: PreparedRagDocument,
        labels: list[str],
    ) -> RagDocumentResult:
        """Persist and embed an already extracted document."""
        return self.strategy.create_document_from_prepared(
            session,
            settings=settings,
            prepared=prepared,
            labels=labels,
        )

    def search(
        self,
        session: Session,
        *,
        settings: Settings,
        labels: list[str],
        query: str,
        limit: int,
    ) -> list[RagSearchResult]:
        """Search chunks with the bound RAG strategy."""
        return self.strategy.search(
            session,
            settings=settings,
            labels=labels,
            query=query,
            limit=limit,
        )
