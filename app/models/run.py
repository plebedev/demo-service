"""SQLAlchemy model for persisted demo runs."""

from datetime import datetime
from enum import StrEnum
import json
from typing import Any

from sqlalchemy import DateTime, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.base import Base


class JsonText(TypeDecorator[Any]):
    """Store JSON payloads in a text column for Oracle compatibility."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        """Serialize Python data to JSON text before persisting it."""
        del dialect
        if value is None:
            return None
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        """Deserialize JSON text back into Python data on reads."""
        del dialect
        if value is None:
            return None
        return json.loads(value)


class RunStatus(StrEnum):
    """Supported persisted states for the phase-1 demo shell."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Run(Base):
    """Stored demo run for the invite-only workflow shell."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    input_text: Mapped[str] = mapped_column(Text(), nullable=True)
    input_metadata_json: Mapped[Any] = mapped_column(JsonText(), nullable=True)
    output_brief_json: Mapped[Any] = mapped_column(JsonText(), nullable=True)
    follow_up_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
