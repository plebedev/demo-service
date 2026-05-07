"""Webhook routes for external provider callbacks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import log_event
from app.db.session import get_db_session
from app.services.notifications import handle_inbound_sms_reply

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/twilio/sms", status_code=status.HTTP_202_ACCEPTED)
async def twilio_sms_webhook(
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, str]:
    """Accept inbound Twilio SMS replies for bounded notification threads."""
    form = await request.form()
    fields = {key: str(value) for key, value in form.items()}
    settings = get_settings()
    signature = request.headers.get("X-Twilio-Signature")
    if signature and settings.twilio_auth_token:
        if not _valid_twilio_signature(
            url=str(request.url),
            fields=fields,
            signature=signature,
            auth_token=settings.twilio_auth_token,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Twilio webhook signature.",
            )
    elif settings.environment != "test":
        log_event(
            logger,
            "twilio_webhook_signature_not_checked",
            level=logging.WARNING,
            reason="missing signature header or auth token",
        )

    from_phone_number = fields.get("From")
    body = fields.get("Body")
    if not from_phone_number or body is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Twilio webhook requires From and Body fields.",
        )

    try:
        await handle_inbound_sms_reply(
            db,
            from_phone_number=from_phone_number,
            body=body,
            provider_message_sid=fields.get("MessageSid") or fields.get("SmsSid"),
            settings=settings,
        )
    except Exception as exc:
        log_event(
            logger,
            "twilio_sms_webhook_failed",
            level=logging.ERROR,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to process inbound SMS.",
        ) from exc
    return {"status": "accepted", "provider": "twilio"}


@router.post("/twilio", status_code=status.HTTP_202_ACCEPTED)
async def twilio_webhook(request: Request) -> dict[str, str]:
    """Accept legacy Twilio webhook pings."""
    await request.body()
    return {"status": "accepted", "provider": "twilio"}


@router.post("/plivo", status_code=status.HTTP_202_ACCEPTED)
async def plivo_webhook(request: Request) -> dict[str, str]:
    """Accept and acknowledge a Plivo webhook payload."""
    await request.body()
    return {"status": "accepted", "provider": "plivo"}


def _valid_twilio_signature(
    *,
    url: str,
    fields: dict[str, str],
    signature: str,
    auth_token: str,
) -> bool:
    """Validate Twilio's request signature for form-encoded webhooks."""
    signed = url + "".join(f"{key}{fields[key]}" for key in sorted(fields))
    digest = hmac.new(
        auth_token.encode("utf-8"),
        signed.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)
