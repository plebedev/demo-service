"""Internal-only admin endpoints for invite management."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from secrets import token_urlsafe
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_secret
from app.core.config import Settings, get_settings
from app.core.experiences import ExperienceId, parse_experience_id
from app.core.logging import log_event
from app.db.models import InvitationCode, InvitationRedemption, InvitationRequest
from app.db.session import get_db_session
from app.schemas.invitations import (
    CreateInvitationCodeRequest,
    IssueInviteCodeDraftRequest,
    IssueInviteCodeDraftResponse,
    InviteEmailDraftResponse,
    InvitationCodeResponse,
    InvitationRequestResponse,
    InvitationRequestReviewRequest,
    InvitationStatsResponse,
)
from app.services.email import EmailDraft, get_email_provider

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/internal/admin/invitations",
    tags=["internal-admin-invitations"],
    dependencies=[Depends(require_admin_secret)],
)


def _optional_experience_id(value: str | None) -> ExperienceId | None:
    """Convert a nullable stored invitation label into a response experience id."""
    if value is None:
        return None
    return parse_experience_id(value)


def _serialize_invitation_code(
    invitation_code: InvitationCode,
) -> InvitationCodeResponse:
    """Convert an ORM invitation code into the API response schema."""
    return InvitationCodeResponse(
        id=invitation_code.id,
        code=invitation_code.code,
        label=_optional_experience_id(invitation_code.label),
        is_active=invitation_code.is_active,
        max_uses=invitation_code.max_uses,
        use_count=invitation_code.use_count,
        created_at=invitation_code.created_at,
        last_used_at=invitation_code.last_used_at,
        invitation_request_id=invitation_code.invitation_request_id,
    )


def _request_code(invite_request: InvitationRequest) -> InvitationCode | None:
    """Return the first code linked to a request, if one exists."""
    if not invite_request.invitation_codes:
        return None
    return sorted(invite_request.invitation_codes, key=lambda code: code.id)[0]


def _serialize_invitation_request(
    invite_request: InvitationRequest,
) -> InvitationRequestResponse:
    """Convert an invitation request into the internal API schema."""
    invitation_code = _request_code(invite_request)
    return InvitationRequestResponse(
        id=invite_request.id,
        name=invite_request.name,
        email=invite_request.email,
        label=_optional_experience_id(invite_request.label),
        reason=invite_request.reason,
        status=invite_request.status,
        created_at=invite_request.created_at,
        reviewed_at=invite_request.reviewed_at,
        reviewer_note=invite_request.reviewer_note,
        fulfillment_status=invite_request.fulfillment_status,
        fulfilled_at=invite_request.fulfilled_at,
        email_sent_at=invite_request.email_sent_at,
        fulfillment_error=invite_request.fulfillment_error,
        issued_invitation_code_id=invitation_code.id if invitation_code else None,
        issued_invitation_code=invitation_code.code if invitation_code else None,
    )


def _serialize_email_draft(
    draft: EmailDraft,
    invite_request: InvitationRequest,
    invitation_code: InvitationCode,
) -> InviteEmailDraftResponse:
    """Convert an email draft into the internal API schema."""
    return InviteEmailDraftResponse(
        provider=draft.provider,
        to_email=draft.to_email,
        subject=draft.subject,
        text_body=draft.text_body,
        html_body=draft.html_body,
        invitation_code_id=invitation_code.id,
        invitation_request_id=invite_request.id,
        send_ready=draft.send_ready,
    )


def _get_invite_request_or_404(
    db: Session, invite_request_id: int
) -> InvitationRequest:
    invite_request = db.get(InvitationRequest, invite_request_id)
    if invite_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite request not found.",
        )
    return invite_request


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
    invite_request = None
    if payload.invitation_request_id is not None:
        invite_request = _get_invite_request_or_404(db, payload.invitation_request_id)

    invitation_code = InvitationCode(
        code=code,
        label=payload.label.value,
        max_uses=payload.max_uses,
        is_active=True,
        use_count=0,
        invitation_request_id=payload.invitation_request_id,
    )
    if invite_request is not None and invite_request.status == "submitted":
        invite_request.status = "reviewed"
        invite_request.reviewed_at = datetime.now(UTC)
    db.add(invitation_code)
    db.commit()
    db.refresh(invitation_code)
    log_event(
        logger,
        "invite_code_created",
        invitation_code_id=invitation_code.id,
        invitation_request_id=invitation_code.invitation_request_id,
    )
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
    log_event(
        logger,
        "invite_code_deactivated",
        invitation_code_id=invitation_code.id,
    )
    return _serialize_invitation_code(invitation_code)


@router.get("/requests", response_model=list[InvitationRequestResponse])
def list_invite_requests(
    db: Session = Depends(get_db_session),
) -> list[InvitationRequestResponse]:
    """List invite requests ordered by most recently submitted."""
    invite_requests = (
        db.query(InvitationRequest)
        .order_by(InvitationRequest.created_at.desc(), InvitationRequest.id.desc())
        .all()
    )
    return [
        _serialize_invitation_request(invite_request)
        for invite_request in invite_requests
    ]


@router.get("/requests/{invite_request_id}", response_model=InvitationRequestResponse)
def get_invite_request(
    invite_request_id: int,
    db: Session = Depends(get_db_session),
) -> InvitationRequestResponse:
    """Return one invite request for operator review."""
    return _serialize_invitation_request(
        _get_invite_request_or_404(db, invite_request_id)
    )


@router.post(
    "/requests/{invite_request_id}/review",
    response_model=InvitationRequestResponse,
)
def review_invite_request(
    invite_request_id: int,
    payload: InvitationRequestReviewRequest,
    db: Session = Depends(get_db_session),
) -> InvitationRequestResponse:
    """Mark an invite request as reviewed, approved, or rejected."""
    invite_request = _get_invite_request_or_404(db, invite_request_id)
    if invite_request.status == "rejected" and payload.status == "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected invite requests cannot be approved in place.",
        )
    invite_request.status = payload.status
    invite_request.reviewed_at = datetime.now(UTC)
    invite_request.reviewer_note = cast(Any, payload.reviewer_note)
    db.add(invite_request)
    db.commit()
    db.refresh(invite_request)
    log_event(
        logger,
        "invite_request_reviewed",
        invitation_request_id=invite_request.id,
        status=invite_request.status,
    )
    return _serialize_invitation_request(invite_request)


@router.post(
    "/requests/{invite_request_id}/issue-code-draft",
    response_model=IssueInviteCodeDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def issue_invite_code_draft(
    invite_request_id: int,
    payload: IssueInviteCodeDraftRequest,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> IssueInviteCodeDraftResponse:
    """Create a linked invite code and return an email draft without sending."""
    invite_request = _get_invite_request_or_404(db, invite_request_id)
    if _request_code(invite_request) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invite request already has an issued invitation code.",
        )
    if invite_request.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected invite requests cannot receive an invitation code.",
        )

    code = payload.code.strip() if payload.code else f"demo-{token_urlsafe(6)}"
    existing = db.query(InvitationCode).filter(InvitationCode.code == code).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation code already exists.",
        )

    invitation_code = InvitationCode(
        code=code,
        label=(
            payload.label.value
            if payload.label
            else invite_request.label or ExperienceId.MESSY_NOTES.value
        ),
        max_uses=payload.max_uses,
        is_active=True,
        use_count=0,
        invitation_request_id=invite_request.id,
    )
    invite_request.status = "approved"
    invite_request.reviewed_at = datetime.now(UTC)
    invite_request.reviewer_note = cast(Any, payload.reviewer_note)
    db.add(invitation_code)
    db.add(invite_request)
    db.commit()
    db.refresh(invite_request)
    db.refresh(invitation_code)

    draft = get_email_provider(settings).build_invite_email(
        invite_request, invitation_code
    )
    log_event(
        logger,
        "invite_request_code_draft_created",
        invitation_request_id=invite_request.id,
        invitation_code_id=invitation_code.id,
    )
    return IssueInviteCodeDraftResponse(
        request=_serialize_invitation_request(invite_request),
        invitation_code=_serialize_invitation_code(invitation_code),
        email_draft=_serialize_email_draft(draft, invite_request, invitation_code),
    )


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
