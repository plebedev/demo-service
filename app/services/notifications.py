"""SMS notification preference, delivery, replies, and opt-out handling."""

from __future__ import annotations

import logging
import re
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import log_event
from app.models.run import Run, RunStatus
from app.models.sms import SmsConversation, SmsMessage, SmsOptOut
from app.schemas.runs import NotificationPreference, NotificationPreferenceRequest
from app.schemas.runs import SmsPhoneStatusResponse
from app.services.runs import _serialize_model
from app.services.twilio import send_sms

logger = logging.getLogger(__name__)

LLM_REPLY_LIMIT = 2
SMS_LIMIT_MESSAGE = (
    "This SMS thread is limited for the demo. Please return to the app for the "
    "full run details."
)
SMS_FALLBACK_MESSAGE = (
    "Thanks for the reply. I could not generate a useful SMS answer right now; "
    "please return to the app for the run details."
)
SMS_OPT_OUT_CONFIRMATION = "Understood - we won't send future messages to this number."

_EXACT_OPT_OUT_MESSAGES = {
    "stop",
    "stopall",
    "unsubscribe",
    "cancel",
    "end",
    "quit",
}


def capture_notification_preference(
    db: Session, run: Run, payload: NotificationPreferenceRequest
) -> Run:
    """Store SMS notification preference after validating phone/block status."""
    if payload.wants_sms and not get_settings().sms_notification_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SMS notifications are not available yet.",
        )
    phone_number = _normalize_us_phone(payload.phone_number)
    if payload.wants_sms and phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Enter a valid US phone number for SMS notification.",
        )
    if payload.wants_sms and phone_number and is_phone_opted_out(db, phone_number):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This number is in the permanent opt-out list.",
        )

    preference = NotificationPreference(
        wants_sms=payload.wants_sms,
        phone_number=phone_number if payload.wants_sms else None,
        phone_number_blocked=False,
    )
    run.notification_preference_serialized = cast(Any, _serialize_model(preference))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def maybe_send_completion_notification(
    db: Session, run: Run, settings: Settings | None = None
) -> None:
    """Send the coded completion SMS if the run preference permits it."""
    settings = settings or get_settings()
    if not settings.sms_notification_enabled:
        return
    preference = _load_notification_preference(run)
    if (
        run.status != RunStatus.COMPLETED.value
        or preference is None
        or not preference.wants_sms
        or not preference.phone_number
    ):
        return

    phone_number = _normalize_us_phone(preference.phone_number)
    if phone_number is None:
        _record_outbound_message(
            db,
            phone_number=preference.phone_number,
            run=run,
            body="",
            status="skipped_invalid_phone",
            error_message="Stored SMS phone number is invalid.",
        )
        return
    if is_phone_opted_out(db, phone_number):
        _record_outbound_message(
            db,
            phone_number=phone_number,
            run=run,
            body="",
            status="skipped_opted_out",
            error_message="Phone number is permanently opted out.",
        )
        return

    conversation = get_or_create_conversation(db, phone_number=phone_number, run=run)
    body = _completion_message(run)
    message = _record_outbound_message(
        db,
        phone_number=phone_number,
        run=run,
        body=body,
        status="attempted",
        conversation=conversation,
    )
    try:
        result = send_sms(settings, to_phone_number=phone_number, body=body)
        message.provider_message_sid = cast(Any, result.provider_message_sid)
        message.status = result.status
    except Exception as exc:
        message.status = "failed"
        message.error_message = str(exc)
        log_event(
            logger,
            "sms_completion_send_failed",
            level=logging.WARNING,
            run_id=run.id,
            phone_number=phone_number,
            error=str(exc),
        )
    db.add(message)
    db.commit()


async def handle_inbound_sms_reply(
    db: Session,
    *,
    from_phone_number: str,
    body: str,
    provider_message_sid: str | None,
    settings: Settings | None = None,
) -> None:
    """Persist an inbound Twilio reply and send the bounded response."""
    settings = settings or get_settings()
    phone_number = _normalize_us_phone(from_phone_number)
    if phone_number is None:
        log_event(
            logger,
            "sms_inbound_invalid_phone",
            level=logging.WARNING,
            from_phone_number=from_phone_number,
        )
        return

    conversation = get_or_create_conversation(db, phone_number=phone_number)
    run = db.get(Run, conversation.run_id) if conversation.run_id else None
    _record_inbound_message(
        db,
        conversation=conversation,
        phone_number=phone_number,
        run=run,
        body=body,
        provider_message_sid=provider_message_sid,
    )

    if await _is_opt_out_message(body, settings):
        upsert_sms_opt_out(
            db,
            phone_number=phone_number,
            source="twilio_reply",
            reason="Inbound SMS opt-out intent.",
        )
        _send_reply(
            db,
            settings=settings,
            conversation=conversation,
            run=run,
            phone_number=phone_number,
            body=SMS_OPT_OUT_CONFIRMATION,
        )
        return

    if is_phone_opted_out(db, phone_number):
        return

    if conversation.llm_reply_count < LLM_REPLY_LIMIT:
        reply = await _generate_reply(body=body, run=run, settings=settings)
        conversation.llm_reply_count += 1
        db.add(conversation)
        db.commit()
    else:
        reply = SMS_LIMIT_MESSAGE

    _send_reply(
        db,
        settings=settings,
        conversation=conversation,
        run=run,
        phone_number=phone_number,
        body=reply,
    )


def get_or_create_conversation(
    db: Session, *, phone_number: str, run: Run | None = None
) -> SmsConversation:
    """Return the latest conversation for a phone/run pair, creating if needed."""
    query = db.query(SmsConversation).filter(
        SmsConversation.phone_number == phone_number
    )
    if run is not None:
        query = query.filter(SmsConversation.run_id == run.id)
    conversation = query.order_by(SmsConversation.id.desc()).first()
    if conversation is not None:
        return conversation
    conversation = SmsConversation(
        phone_number=phone_number,
        run_id=run.id if run is not None else None,
        llm_reply_count=0,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def is_phone_opted_out(db: Session, phone_number: str) -> bool:
    """Return whether a normalized phone number is permanently blocked."""
    normalized = _normalize_us_phone(phone_number)
    if normalized is None:
        return False
    return db.get(SmsOptOut, normalized) is not None


def upsert_sms_opt_out(
    db: Session, *, phone_number: str, source: str, reason: str | None
) -> SmsOptOut:
    """Persist a permanent SMS opt-out entry."""
    normalized = _normalize_us_phone(phone_number)
    if normalized is None:
        raise ValueError("Cannot opt out an invalid phone number.")
    opt_out = db.get(SmsOptOut, normalized)
    if opt_out is None:
        opt_out = SmsOptOut(phone_number=normalized, source=source, reason=reason)
    else:
        opt_out.source = source
        opt_out.reason = cast(Any, reason)
    db.add(opt_out)
    db.commit()
    db.refresh(opt_out)
    return opt_out


def enrich_notification_preference(
    db: Session, preference: NotificationPreference | None
) -> NotificationPreference | None:
    """Attach current permanent block-list status to a run preference."""
    if preference is None or preference.phone_number is None:
        return preference
    return preference.model_copy(
        update={"phone_number_blocked": is_phone_opted_out(db, preference.phone_number)}
    )


def get_sms_phone_status(
    db: Session, phone_number: str | None
) -> SmsPhoneStatusResponse:
    """Return normalized SMS validation and permanent block-list status."""
    normalized = _normalize_us_phone(phone_number)
    if normalized is None:
        return SmsPhoneStatusResponse(
            valid=False, phone_number=None, phone_number_blocked=False
        )
    return SmsPhoneStatusResponse(
        valid=True,
        phone_number=normalized,
        phone_number_blocked=is_phone_opted_out(db, normalized),
    )


def _normalize_us_phone(phone_number: str | None) -> str | None:
    if phone_number is None or not phone_number.strip():
        return None
    digits = re.sub(r"\D+", "", phone_number)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    if digits[0] in {"0", "1"} or digits[3] in {"0", "1"}:
        return None
    return f"+1{digits}"


def _load_notification_preference(run: Run) -> NotificationPreference | None:
    if run.notification_preference_serialized is None:
        return None
    return NotificationPreference.model_validate_json(
        run.notification_preference_serialized
    )


def _completion_message(run: Run) -> str:
    title = run.title or f"Run #{run.id}"
    return (
        f"Your messy-notes run is complete: {title}. "
        "Open the demo app to review the brief and audit summary."
    )


def _record_outbound_message(
    db: Session,
    *,
    phone_number: str,
    run: Run | None,
    body: str,
    status: str,
    conversation: SmsConversation | None = None,
    error_message: str | None = None,
) -> SmsMessage:
    message = SmsMessage(
        conversation_id=conversation.id if conversation is not None else None,
        run_id=run.id if run is not None else None,
        phone_number=phone_number,
        direction="outbound",
        body=body,
        provider="twilio",
        status=status,
        error_message=error_message,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _record_inbound_message(
    db: Session,
    *,
    conversation: SmsConversation,
    phone_number: str,
    run: Run | None,
    body: str,
    provider_message_sid: str | None,
) -> SmsMessage:
    message = SmsMessage(
        conversation_id=conversation.id,
        run_id=run.id if run is not None else None,
        phone_number=phone_number,
        direction="inbound",
        body=body,
        provider="twilio",
        provider_message_sid=provider_message_sid,
        status="received",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


async def _is_opt_out_message(body: str, settings: Settings) -> bool:
    normalized = re.sub(r"[^a-z]+", "", body.lower())
    if normalized in _EXACT_OPT_OUT_MESSAGES:
        return True
    try:
        from app.services.sms_ai import classify_opt_out_with_llm

        return (await classify_opt_out_with_llm(body, settings)).is_opt_out
    except Exception as exc:
        log_event(
            logger,
            "sms_opt_out_classification_failed",
            level=logging.WARNING,
            error=str(exc),
        )
        return False


async def _generate_reply(*, body: str, run: Run | None, settings: Settings) -> str:
    try:
        from app.services.sms_ai import generate_sms_reply_with_llm

        reply = await generate_sms_reply_with_llm(
            inbound_body=body,
            run=run,
            settings=settings,
        )
        return reply or SMS_FALLBACK_MESSAGE
    except Exception as exc:
        log_event(
            logger,
            "sms_reply_generation_failed",
            level=logging.WARNING,
            run_id=run.id if run is not None else None,
            error=str(exc),
        )
        return SMS_FALLBACK_MESSAGE


def _send_reply(
    db: Session,
    *,
    settings: Settings,
    conversation: SmsConversation,
    run: Run | None,
    phone_number: str,
    body: str,
) -> None:
    message = _record_outbound_message(
        db,
        phone_number=phone_number,
        run=run,
        body=body,
        status="attempted",
        conversation=conversation,
    )
    try:
        result = send_sms(settings, to_phone_number=phone_number, body=body)
        message.provider_message_sid = cast(Any, result.provider_message_sid)
        message.status = result.status
    except Exception as exc:
        message.status = "failed"
        message.error_message = str(exc)
        log_event(
            logger,
            "sms_reply_send_failed",
            level=logging.WARNING,
            run_id=run.id if run is not None else None,
            phone_number=phone_number,
            error=str(exc),
        )
    db.add(message)
    db.commit()
