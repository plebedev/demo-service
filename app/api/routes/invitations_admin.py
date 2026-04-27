"""Internal-only admin endpoints for invite management."""

from __future__ import annotations

from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_secret
from app.db.models import InvitationCode, InvitationRedemption
from app.db.session import get_db_session
from app.schemas.invitations import (
    CreateInvitationCodeRequest,
    InvitationCodeResponse,
    InvitationStatsResponse,
)

router = APIRouter(
    prefix="/api/internal/admin/invitations",
    tags=["internal-admin-invitations"],
    dependencies=[Depends(require_admin_secret)],
)


def _serialize_invitation_code(
    invitation_code: InvitationCode,
) -> InvitationCodeResponse:
    """Convert an ORM invitation code into the API response schema."""
    return InvitationCodeResponse(
        id=invitation_code.id,
        code=invitation_code.code,
        label=invitation_code.label,
        is_active=invitation_code.is_active,
        max_uses=invitation_code.max_uses,
        use_count=invitation_code.use_count,
        created_at=invitation_code.created_at,
        last_used_at=invitation_code.last_used_at,
    )


@router.post(
    "", response_model=InvitationCodeResponse, status_code=status.HTTP_201_CREATED
)
def create_invitation_code(
    payload: CreateInvitationCodeRequest,
    db: Session = Depends(get_db_session),
) -> InvitationCodeResponse:
    """Create a new invitation code for the internal demo operator."""
    code = payload.code.strip() if payload.code else f"demo-{token_urlsafe(6)}"
    existing = db.query(InvitationCode).filter(InvitationCode.code == code).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation code already exists.",
        )

    invitation_code = InvitationCode(
        code=code,
        label=payload.label,
        max_uses=payload.max_uses,
        is_active=True,
        use_count=0,
    )
    db.add(invitation_code)
    db.commit()
    db.refresh(invitation_code)
    return _serialize_invitation_code(invitation_code)


@router.get("", response_model=list[InvitationCodeResponse])
def list_invitation_codes(
    db: Session = Depends(get_db_session),
) -> list[InvitationCodeResponse]:
    """List invitation codes ordered by most recently created."""
    invitation_codes = (
        db.query(InvitationCode).order_by(InvitationCode.created_at.desc()).all()
    )
    return [
        _serialize_invitation_code(invitation_code)
        for invitation_code in invitation_codes
    ]


@router.post("/{invitation_code_id}/deactivate", response_model=InvitationCodeResponse)
def deactivate_invitation_code(
    invitation_code_id: int,
    db: Session = Depends(get_db_session),
) -> InvitationCodeResponse:
    """Deactivate a code so it can no longer be redeemed."""
    invitation_code = db.get(InvitationCode, invitation_code_id)
    if invitation_code is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation code not found.",
        )

    invitation_code.is_active = False
    db.commit()
    db.refresh(invitation_code)
    return _serialize_invitation_code(invitation_code)


@router.get("/stats", response_model=InvitationStatsResponse)
def invitation_stats(db: Session = Depends(get_db_session)) -> InvitationStatsResponse:
    """Return aggregate and per-code invitation usage statistics."""
    invitation_codes = (
        db.query(InvitationCode).order_by(InvitationCode.created_at.desc()).all()
    )
    total_redemptions = db.scalar(
        select(func.count()).select_from(InvitationRedemption)
    )
    active_codes = sum(
        1 for invitation_code in invitation_codes if invitation_code.is_active
    )

    return InvitationStatsResponse(
        total_codes=len(invitation_codes),
        active_codes=active_codes,
        total_redemptions=total_redemptions or 0,
        codes=[
            _serialize_invitation_code(invitation_code)
            for invitation_code in invitation_codes
        ],
    )
