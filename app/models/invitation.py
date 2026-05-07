"""SQLAlchemy models for invite-only access control."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InvitationCode(Base):
    """Redeemable invitation code for access to the phase-1 demo."""

    __tablename__ = "invitation_codes"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    code: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False
    )  # redeemable code string entered by the user
    label: Mapped[str] = mapped_column(
        String(255), nullable=True
    )  # experience label this code grants access to
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )  # False when the code has been deactivated
    max_uses: Mapped[int] = mapped_column(
        Integer, nullable=True
    )  # maximum allowed redemptions; null means unlimited
    use_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # number of times this code has been redeemed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # timestamp of the most recent redemption
    invitation_request_id: Mapped[int] = mapped_column(
        ForeignKey("invitation_requests.id"), nullable=True
    )  # FK to the invite request this code was created to fulfill

    redemptions: Mapped[list["InvitationRedemption"]] = relationship(
        back_populates="invitation_code", cascade="all, delete-orphan"
    )
    invitation_request: Mapped["InvitationRequest"] = relationship(
        back_populates="invitation_codes"
    )


class InvitationRedemption(Base):
    """Redemption record for one issued access token."""

    __tablename__ = "invitation_redemptions"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    invitation_code_id: Mapped[int] = mapped_column(
        ForeignKey("invitation_codes.id"), nullable=False
    )  # FK to the code that was redeemed
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )  # timestamp of the redemption
    token_id: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # unique identifier embedded in the issued JWT
    user_agent: Mapped[str] = mapped_column(
        String(512), nullable=True
    )  # HTTP User-Agent header from the redemption request
    ip_hash: Mapped[str] = mapped_column(
        String(64), nullable=True
    )  # hashed client IP address for audit purposes

    invitation_code: Mapped[InvitationCode] = relationship(back_populates="redemptions")


class InvitationRequest(Base):
    """Public request for automatic invite fulfillment."""

    __tablename__ = "invitation_requests"

    id: Mapped[int] = mapped_column(
        Integer, Identity(), primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # applicant's full name
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, index=True
    )  # applicant's email address
    label: Mapped[str] = mapped_column(
        String(255), nullable=True
    )  # experience label requested
    reason: Mapped[str] = mapped_column(
        Text(), nullable=False
    )  # applicant's stated reason for requesting access
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="submitted", server_default="submitted"
    )  # review status: 'submitted', 'reviewed', 'approved', or 'rejected'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_agent: Mapped[str] = mapped_column(
        String(512), nullable=True
    )  # HTTP User-Agent header from the submission request
    ip_hash: Mapped[str] = mapped_column(
        String(64), nullable=True
    )  # hashed client IP address for audit purposes
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # timestamp when an operator reviewed the request
    reviewer_note: Mapped[str] = mapped_column(
        Text(), nullable=True
    )  # operator note recorded at review time
    fulfillment_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )  # fulfillment pipeline status: 'pending', 'fulfilled', or 'failed'
    fulfilled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # timestamp when an invite code was issued to the applicant
    email_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # timestamp when the invite email was delivered
    fulfillment_error: Mapped[str] = mapped_column(
        Text(), nullable=True
    )  # error detail if the fulfillment pipeline failed

    invitation_codes: Mapped[list[InvitationCode]] = relationship(
        back_populates="invitation_request"
    )
