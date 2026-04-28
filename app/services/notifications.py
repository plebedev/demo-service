"""Notification preference capture for future completion messaging."""

from __future__ import annotations

import re
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.run import Run
from app.schemas.runs import NotificationPreference, NotificationPreferenceRequest
from app.services.runs import _serialize_model


def capture_notification_preference(
    db: Session, run: Run, payload: NotificationPreferenceRequest
) -> Run:
    """Store SMS notification preference without sending SMS."""
    phone_number = _normalize_us_phone(payload.phone_number)
    if payload.wants_sms and phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Enter a valid US phone number for SMS notification.",
        )

    preference = NotificationPreference(
        wants_sms=payload.wants_sms,
        phone_number=phone_number if payload.wants_sms else None,
    )
    run.notification_preference_serialized = cast(Any, _serialize_model(preference))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def maybe_send_completion_notification(run: Run) -> None:
    """Leave a coded hook for future SMS delivery after completion."""
    del run


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
