"""SQLAlchemy models for bounded SMS notification handling."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SmsConversation(Base):
    """Per-phone/run state for the limited SMS reply flow."""

    __tablename__ = "sms_conversations"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    phone_number: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    llm_reply_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SmsMessage(Base):
    """Inbound and outbound SMS records for audit and troubleshooting."""

    __tablename__ = "sms_messages"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("sms_conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    phone_number: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text(), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="twilio")
    provider_message_sid: Mapped[str] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SmsOptOut(Base):
    """Permanent SMS block-list entry."""

    __tablename__ = "sms_opt_outs"

    phone_number: Mapped[str] = mapped_column(String(16), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="inbound")
    reason: Mapped[str] = mapped_column(Text(), nullable=True)
    opted_out_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
