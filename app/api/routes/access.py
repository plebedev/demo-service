"""Invite redemption and token verification endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_access_token
from app.core.config import Settings, get_settings
from app.core.phase1 import build_phase1_guardrails
from app.core.security import AccessTokenClaims
from app.core.security import create_access_token, hash_ip_address
from app.db.models import InvitationCode, InvitationRedemption
from app.db.session import get_db_session
from app.schemas.access import (
    AccessTokenResponse,
    AccessTokenVerificationResponse,
    RedeemInvitationRequest,
)

router = APIRouter(prefix="/api/access", tags=["access"])


@router.post("/redeem", response_model=AccessTokenResponse)
def redeem_invitation_code(
    payload: RedeemInvitationRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AccessTokenResponse:
    """Validate an invitation code, issue a signed access token, and record usage."""
    normalized_code = payload.code.strip()
    invitation_code = (
        db.query(InvitationCode).filter(InvitationCode.code == normalized_code).first()
    )
    if invitation_code is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation code not found.",
        )
    if not invitation_code.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invitation code is inactive.",
        )
    if (
        invitation_code.max_uses is not None
        and invitation_code.use_count >= invitation_code.max_uses
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invitation code has reached its usage limit.",
        )

    access_token, claims = create_access_token(
        settings=settings,
        invitation_code_id=invitation_code.id,
        code=invitation_code.code,
    )
    invitation_code.use_count += 1
    invitation_code.last_used_at = datetime.now(UTC)
    db.add(
        InvitationRedemption(
            invitation_code_id=invitation_code.id,
            token_id=claims.token_id,
            user_agent=request.headers.get("user-agent"),
            ip_hash=hash_ip_address(
                request.client.host if request.client is not None else None, settings
            ),
        )
    )
    db.commit()

    return AccessTokenResponse(
        access_token=access_token,
        expires_at=claims.expires_at,
        phase1=build_phase1_guardrails(settings),
    )


@router.get("/verify", response_model=AccessTokenVerificationResponse)
def verify_access(
    claims: AccessTokenClaims = Depends(get_current_access_token),
    settings: Settings = Depends(get_settings),
) -> AccessTokenVerificationResponse:
    """Confirm that a previously stored access token is still valid."""
    return AccessTokenVerificationResponse(
        status="ok",
        token_id=claims.token_id,
        expires_at=claims.expires_at,
        phase1=build_phase1_guardrails(settings),
    )
