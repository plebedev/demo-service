"""SQLAlchemy model for structured run execution events."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunEventType(StrEnum):
    """Supported run-event types for workflow auditing."""

    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    HANDOFF_OCCURRED = "handoff_occurred"
    RUN_COMPLETED = "run_completed"
    POST_PROCESSOR_SCHEDULED = "post_processor_scheduled"


class RunEvent(Base):
    """Persisted event emitted during workflow execution."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_role: Mapped[str] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=True)
    tool_arguments_serialized: Mapped[str] = mapped_column(
        "tool_arguments_json", Text(), nullable=True
    )
    tool_result_serialized: Mapped[str] = mapped_column(
        "tool_result_json", Text(), nullable=True
    )
    handoff_source_role: Mapped[str] = mapped_column(String(128), nullable=True)
    handoff_target_role: Mapped[str] = mapped_column(String(128), nullable=True)
    post_processor_key: Mapped[str] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
