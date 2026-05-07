"""SQLAlchemy model for structured run execution events."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunEventType(StrEnum):
    """Supported run-event types for workflow auditing."""

    RUN_EXECUTION_STARTED = "run_execution_started"
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    HANDOFF_OCCURRED = "handoff_occurred"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    POST_PROCESSOR_STARTED = "post_processor_started"
    POST_PROCESSOR_COMPLETED = "post_processor_completed"


class RunEvent(Base):
    """Persisted event emitted during workflow execution."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )  # FK to the run that emitted this event
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # event category (see RunEventType)
    status: Mapped[str] = mapped_column(
        String(32), nullable=True
    )  # optional status string associated with the event
    agent_role: Mapped[str] = mapped_column(
        String(128), nullable=True
    )  # role identifier of the agent that emitted this event
    tool_name: Mapped[str] = mapped_column(
        String(128), nullable=True
    )  # name of the tool involved in a TOOL_CALLED or TOOL_RESULT event
    tool_arguments_serialized: Mapped[str] = mapped_column(
        "tool_arguments_json", Text(), nullable=True
    )  # serialized arguments passed to the tool call
    tool_result_serialized: Mapped[str] = mapped_column(
        "tool_result_json", Text(), nullable=True
    )  # serialized result returned by the tool
    handoff_source_role: Mapped[str] = mapped_column(
        String(128), nullable=True
    )  # role of the agent that initiated the handoff
    handoff_target_role: Mapped[str] = mapped_column(
        String(128), nullable=True
    )  # role of the agent that received the handoff
    post_processor_key: Mapped[str] = mapped_column(
        String(128), nullable=True
    )  # key identifying the post-processor that emitted this event
    message: Mapped[str] = mapped_column(
        Text(), nullable=True
    )  # optional human-readable event detail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
