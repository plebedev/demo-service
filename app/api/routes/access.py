"""Invite redemption and token verification endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_access_token
from app.core.config import Settings, get_settings
from app.core.logging import log_event
from app.core.phase1 import build_phase1_guardrails
from app.core.security import AccessTokenClaims
from app.core.security import create_access_token, hash_ip_address
from app.db.models import InvitationCode, InvitationRedemption, InvitationRequest
from app.db.session import get_db_session
from app.schemas.access import (
    AccessTokenResponse,
    AccessTokenVerificationResponse,
    InviteRequestCreate,
    InviteRequestResponse,
    RedeemInvitationRequest,
)

router = APIRouter(prefix="/api/access", tags=["access"])
logger = logging.getLogger(__name__)


@router.post(
    "/invite-requests",
    response_model=InviteRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invite_request(
    payload: InviteRequestCreate,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> InviteRequestResponse:
    """Persist a public invite request for later manual review."""
    invite_request = InvitationRequest(
        name=payload.name,
        email=payload.email,
        reason=payload.reason,
        user_agent=request.headers.get("user-agent"),
        ip_hash=hash_ip_address(
            request.client.host if request.client is not None else None, settings
        ),
    )
    db.add(invite_request)
    db.commit()
    db.refresh(invite_request)
    log_event(
        logger,
        "invite_request_submitted",
        invitation_request_id=invite_request.id,
        email=invite_request.email,
    )
    return InviteRequestResponse(
        id=invite_request.id,
        status=invite_request.status,
        message="Invite request received for manual review.",
    )


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
