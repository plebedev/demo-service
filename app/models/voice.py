"""SQLAlchemy models for voice experience configuration and personas."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    Identity,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VoiceExperienceConfig(Base):
    """Per-experience voice configuration including the synthesized greeting."""

    __tablename__ = "voice_experience_configs"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    experience_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    voice_name: Mapped[str] = mapped_column(
        String(128), nullable=False
    )  # provider API voice identifier, e.g. "eve" (xAI) or "alloy" (OpenAI)
    voice_provider: Mapped[str] = mapped_column(
        String(32), nullable=True
    )  # per-experience provider override; if null, falls back to global VOICE_PROVIDER setting
    synthesized_greeting: Mapped[str] = mapped_column(
        Text(), nullable=True
    )  # LLM-generated greeting; regenerated when active personas change
    greeting_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # timestamp of last greeting synthesis
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VoicePersona(Base):
    """Experience-scoped voice assistant persona with embedded guidance."""

    __tablename__ = "voice_personas"
    __table_args__ = (
        UniqueConstraint(
            "experience_id",
            "name_key",
            "is_active",
            name="uq_voice_personas_experience_name_active",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    experience_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # experience this persona belongs to (e.g. 'voice-demo')
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # display name
    name_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # normalized name used for uniqueness checks
    instructions: Mapped[str] = mapped_column(
        Text(), nullable=False
    )  # system-level instructions for the xAI voice agent session
    capabilities_serialized: Mapped[str] = mapped_column(
        "capabilities_json", Text(), nullable=True
    )  # structured description of what this persona handles; used for greeting synthesis and routing
    tool_config_serialized: Mapped[str] = mapped_column(
        "tool_config_json", Text(), nullable=True
    )  # curated guidance: intake questions, scoring rules, recommendation templates
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
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


class VoiceConversationRecord(Base):
    """Persisted record of a completed voice conversation, including transcript and cost."""

    __tablename__ = "voice_conversation_records"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    experience_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    call_sid: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )  # browser UUID or Twilio CallSid
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # 'xai' or 'openai'
    voice: Mapped[str] = mapped_column(
        String(128), nullable=False
    )  # provider API voice identifier used for this conversation
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float] = mapped_column(
        Float, nullable=True
    )  # wall-clock duration
    input_audio_seconds: Mapped[float] = mapped_column(
        Float, nullable=True
    )  # seconds of audio sent by the user (bytes / 8000)
    output_audio_seconds: Mapped[float] = mapped_column(
        Float, nullable=True
    )  # seconds of audio sent by the advisor (bytes / 8000)
    estimated_cost_usd: Mapped[float] = mapped_column(
        Float, nullable=True
    )  # duration-based cost estimate in USD
    transcript_json: Mapped[str] = mapped_column(
        Text(), nullable=False, default="[]"
    )  # JSON array of transcript entries (role + text/tool_name/args)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
