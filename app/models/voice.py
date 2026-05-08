"""SQLAlchemy models for voice experience configuration and personas."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
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
    )  # consistent voice character name shown to callers
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
