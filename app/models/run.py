"""SQLAlchemy model for persisted demo runs."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


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
    workflow_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="messy-notes-v1",
        server_default="messy-notes-v1",
    )
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
    normalized_input_text: Mapped[str] = mapped_column(Text(), nullable=True)
    input_metadata_serialized: Mapped[str] = mapped_column(
        "input_metadata_json", Text(), nullable=True
    )
    uploaded_files_serialized: Mapped[str] = mapped_column(
        "uploaded_files_json", Text(), nullable=True
    )
    ingestion_summary_serialized: Mapped[str] = mapped_column(
        "ingestion_summary_json", Text(), nullable=True
    )
    output_brief_serialized: Mapped[str] = mapped_column(
        "output_brief_json", Text(), nullable=True
    )
    post_processor_results_serialized: Mapped[str] = mapped_column(
        "post_processor_results_json", Text(), nullable=True
    )
    follow_up_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    follow_up_response_serialized: Mapped[str] = mapped_column(
        "follow_up_response_json", Text(), nullable=True
    )
    notification_preference_serialized: Mapped[str] = mapped_column(
        "notification_preference_json", Text(), nullable=True
    )
