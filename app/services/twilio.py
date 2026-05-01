"""Small Twilio SMS provider boundary."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib import parse, request

from app.core.config import Settings


@dataclass(frozen=True)
class SmsSendResult:
    """Provider send result persisted by the notification service."""

    provider_message_sid: str | None
    status: str


class TwilioConfigurationError(RuntimeError):
    """Raised when Twilio credentials are not configured."""


class TwilioSendError(RuntimeError):
    """Raised when Twilio rejects or fails a send."""


def send_sms(settings: Settings, *, to_phone_number: str, body: str) -> SmsSendResult:
    """Send one SMS using Twilio's Messages API."""
    if (
        not settings.twilio_account_sid
        or not settings.twilio_auth_token
        or not settings.twilio_from_number
    ):
        raise TwilioConfigurationError("Twilio SMS credentials are not configured.")

    url = (
        "https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.twilio_account_sid}/Messages.json"
    )
    payload = parse.urlencode(
        {
            "To": to_phone_number,
            "From": settings.twilio_from_number,
            "Body": body,
        }
    ).encode("utf-8")
    token = base64.b64encode(
        f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode("utf-8")
    ).decode("ascii")
    http_request = request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=10) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise TwilioSendError(str(exc)) from exc

    if not isinstance(decoded, dict):
        raise TwilioSendError("Twilio response was not a JSON object.")
    return SmsSendResult(
        provider_message_sid=_string_or_none(decoded.get("sid")),
        status=_string_or_none(decoded.get("status")) or "sent",
    )


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
