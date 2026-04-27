"""SQLAlchemy models for invite-only access control."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Identity, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InvitationCode(Base):
    """Redeemable invitation code for access to the phase-1 demo."""

    __tablename__ = "invitation_codes"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    redemptions: Mapped[list["InvitationRedemption"]] = relationship(
        back_populates="invitation_code", cascade="all, delete-orphan"
    )


class InvitationRedemption(Base):
    """Redemption record for one issued access token."""

    __tablename__ = "invitation_redemptions"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    invitation_code_id: Mapped[int] = mapped_column(
        ForeignKey("invitation_codes.id"), nullable=False
    )
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    token_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(512), nullable=True)
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=True)

    invitation_code: Mapped[InvitationCode] = relationship(back_populates="redemptions")
