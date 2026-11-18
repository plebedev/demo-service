"""SQLAlchemy model for durably completed workflow execution steps."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunExecutionStep(Base):
    """Checkpoint for one completed step of the current run execution."""

    __tablename__ = "run_execution_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_run_execution_steps_key"),
    )

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )  # FK to the run whose execution produced this checkpoint
    step_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # deterministic ordinal + step label, e.g. 003:tool:orchestrator:normalize
    output_serialized: Mapped[str] = mapped_column(
        "output_json", Text(), nullable=True
    )  # serialized step output needed to restore later steps on resume
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
