"""Tests for Twilio SMS delivery, replies, and opt-out blocking."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.config import get_settings
from app.db.models import Run, SmsConversation, SmsMessage, SmsOptOut
from app.models.run import RunStatus
from app.schemas.runs import NotificationPreferenceRequest
from app.services.notifications import (
    SMS_FALLBACK_MESSAGE,
    SMS_LIMIT_MESSAGE,
    capture_notification_preference,
    get_sms_phone_status,
    handle_inbound_sms_reply,
    maybe_send_completion_notification,
    upsert_sms_opt_out,
)
from app.services.runs import create_run
from app.services.twilio import TwilioConfigurationError, send_sms
from app.schemas.runs import RunCreateRequest


def _completed_run(db_session) -> Run:
    run = create_run(
        db_session,
        RunCreateRequest(title="Board prep", input_text="Decision approved"),
    )
    run.status = RunStatus.COMPLETED.value
    run.output_brief_serialized = json.dumps(
        {"title": "Board prep", "executive_summary": "Decision approved."}
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def test_twilio_sms_webhook_stores_inbound_reply(
    client, db_session, monkeypatch
) -> None:
    replies: list[str] = []

    async def fake_classifier(message_body, settings):
        del message_body, settings
        return type("Classification", (), {"is_opt_out": False})()

    async def fake_reply(*, inbound_body: str, run: Run | None, settings):
        del inbound_body, run, settings
        return "Reply from model"

    def fake_send(settings, *, to_phone_number: str, body: str):
        del settings, to_phone_number
        replies.append(body)
        return type("Result", (), {"provider_message_sid": None, "status": "sent"})()

    monkeypatch.setattr(
        "app.services.sms_ai.classify_opt_out_with_llm", fake_classifier
    )
    monkeypatch.setattr("app.services.sms_ai.generate_sms_reply_with_llm", fake_reply)
    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)

    response = client.post(
        "/api/webhooks/twilio/sms",
        data={
            "From": "+14155550134",
            "Body": "Is it done?",
            "MessageSid": "SMINBOUND",
        },
    )

    assert response.status_code == 202
    inbound = db_session.query(SmsMessage).filter_by(direction="inbound").one()
    assert inbound.body == "Is it done?"
    assert inbound.provider_message_sid == "SMINBOUND"
    assert replies == ["Reply from model"]


def test_sms_notification_is_sent_on_completion_when_opted_in(
    db_session, monkeypatch
) -> None:
    run = _completed_run(db_session)
    capture_notification_preference(
        db_session,
        run,
        NotificationPreferenceRequest(wants_sms=True, phone_number="(415) 555-0134"),
    )
    sent: list[tuple[str, str]] = []

    def fake_send(settings, *, to_phone_number: str, body: str):
        del settings
        sent.append((to_phone_number, body))
        return type("Result", (), {"provider_message_sid": "SM123", "status": "sent"})()

    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)

    maybe_send_completion_notification(db_session, run, get_settings())

    assert sent == [("+14155550134", sent[0][1])]
    message = db_session.query(SmsMessage).one()
    assert message.status == "sent"
    assert message.provider_message_sid == "SM123"


def test_sms_feature_flag_blocks_preference_and_send(db_session, monkeypatch) -> None:
    run = _completed_run(db_session)
    disabled_settings = get_settings().model_copy(
        update={"sms_notification_enabled": False}
    )
    monkeypatch.setattr(
        "app.services.notifications.get_settings",
        lambda: disabled_settings,
    )

    with pytest.raises(Exception) as exc_info:
        capture_notification_preference(
            db_session,
            run,
            NotificationPreferenceRequest(
                wants_sms=True, phone_number="(415) 555-0134"
            ),
        )
    assert "not available" in str(exc_info.value)

    run.notification_preference_serialized = (
        '{"wants_sms":true,"phone_number":"+14155550134"}'
    )
    called = False

    def fake_send(settings, *, to_phone_number: str, body: str):
        nonlocal called
        del settings, to_phone_number, body
        called = True

    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)

    maybe_send_completion_notification(db_session, run, disabled_settings)

    assert called is False
    assert db_session.query(SmsMessage).count() == 0


def test_blocked_numbers_do_not_receive_completion_sms(db_session, monkeypatch) -> None:
    run = _completed_run(db_session)
    run.notification_preference_serialized = (
        '{"wants_sms":true,"phone_number":"+14155550134"}'
    )
    upsert_sms_opt_out(
        db_session,
        phone_number="+14155550134",
        source="test",
        reason="blocked",
    )
    called = False

    def fake_send(settings, *, to_phone_number: str, body: str):
        nonlocal called
        del settings, to_phone_number, body
        called = True

    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)

    maybe_send_completion_notification(db_session, run, get_settings())

    assert called is False
    message = db_session.query(SmsMessage).one()
    assert message.status == "skipped_opted_out"


def test_inbound_webhook_stores_reply_and_uses_first_two_llm_turns(
    db_session, monkeypatch
) -> None:
    run = _completed_run(db_session)
    conversation = SmsConversation(phone_number="+14155550134", run_id=run.id)
    db_session.add(conversation)
    db_session.commit()
    replies: list[str] = []

    async def fake_classifier(message_body, settings):
        del message_body, settings
        return type("Classification", (), {"is_opt_out": False})()

    async def fake_reply(*, inbound_body: str, run: Run | None, settings):
        del run, settings
        return f"AI reply to {inbound_body}"

    def fake_send(settings, *, to_phone_number: str, body: str):
        del settings, to_phone_number
        replies.append(body)
        return type("Result", (), {"provider_message_sid": None, "status": "sent"})()

    monkeypatch.setattr(
        "app.services.sms_ai.classify_opt_out_with_llm", fake_classifier
    )
    monkeypatch.setattr("app.services.sms_ai.generate_sms_reply_with_llm", fake_reply)
    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)

    asyncio.run(
        handle_inbound_sms_reply(
            db_session,
            from_phone_number="+14155550134",
            body="What changed?",
            provider_message_sid="SMIN1",
            settings=get_settings(),
        )
    )
    asyncio.run(
        handle_inbound_sms_reply(
            db_session,
            from_phone_number="+14155550134",
            body="Any risks?",
            provider_message_sid="SMIN2",
            settings=get_settings(),
        )
    )
    asyncio.run(
        handle_inbound_sms_reply(
            db_session,
            from_phone_number="+14155550134",
            body="One more?",
            provider_message_sid="SMIN3",
            settings=get_settings(),
        )
    )

    assert replies == [
        "AI reply to What changed?",
        "AI reply to Any risks?",
        SMS_LIMIT_MESSAGE,
    ]
    db_session.refresh(conversation)
    assert conversation.llm_reply_count == 2
    assert db_session.query(SmsMessage).filter_by(direction="inbound").count() == 3


def test_exact_opt_out_persists_block_and_prevents_future_sends(
    db_session, monkeypatch
) -> None:
    run = _completed_run(db_session)
    conversation = SmsConversation(phone_number="+14155550134", run_id=run.id)
    db_session.add(conversation)
    db_session.commit()
    replies: list[str] = []

    def fake_send(settings, *, to_phone_number: str, body: str):
        del settings, to_phone_number
        replies.append(body)
        return type("Result", (), {"provider_message_sid": None, "status": "sent"})()

    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)

    asyncio.run(
        handle_inbound_sms_reply(
            db_session,
            from_phone_number="+1 (415) 555-0134",
            body="STOP",
            provider_message_sid="SMSTOP",
            settings=get_settings(),
        )
    )

    assert db_session.get(SmsOptOut, "+14155550134") is not None
    assert "won't send future messages" in replies[0]
    run.notification_preference_serialized = (
        '{"wants_sms":true,"phone_number":"+14155550134"}'
    )
    maybe_send_completion_notification(db_session, run, get_settings())
    assert db_session.query(SmsMessage).filter_by(status="skipped_opted_out").count()


def test_classifier_opt_out_path_persists_block(db_session, monkeypatch) -> None:
    async def fake_classifier(message_body, settings):
        del message_body, settings
        return type("Classification", (), {"is_opt_out": True})()

    def fake_send(settings, *, to_phone_number: str, body: str):
        del settings, to_phone_number, body
        return type("Result", (), {"provider_message_sid": None, "status": "sent"})()

    monkeypatch.setattr(
        "app.services.sms_ai.classify_opt_out_with_llm", fake_classifier
    )
    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)

    asyncio.run(
        handle_inbound_sms_reply(
            db_session,
            from_phone_number="415-555-0134",
            body="please remove me from these updates",
            provider_message_sid="SMCLASS",
            settings=get_settings(),
        )
    )

    assert db_session.get(SmsOptOut, "+14155550134") is not None


def test_fallbacks_for_reply_and_classifier_failures(db_session, monkeypatch) -> None:
    replies: list[str] = []

    async def broken_classifier(message_body, settings):
        del message_body, settings
        raise RuntimeError("classifier down")

    async def broken_reply(*, inbound_body: str, run: Run | None, settings):
        del inbound_body, run, settings
        raise RuntimeError("reply down")

    def fake_send(settings, *, to_phone_number: str, body: str):
        del settings, to_phone_number
        replies.append(body)
        return type("Result", (), {"provider_message_sid": None, "status": "sent"})()

    monkeypatch.setattr(
        "app.services.sms_ai.classify_opt_out_with_llm", broken_classifier
    )
    monkeypatch.setattr("app.services.sms_ai.generate_sms_reply_with_llm", broken_reply)
    monkeypatch.setattr("app.services.notifications.send_sms", fake_send)

    asyncio.run(
        handle_inbound_sms_reply(
            db_session,
            from_phone_number="415-555-0134",
            body="Can you summarize?",
            provider_message_sid="SMFAIL",
            settings=get_settings(),
        )
    )

    assert replies == [SMS_FALLBACK_MESSAGE]


def test_validation_prevents_blocked_number_for_notification_preference(
    db_session,
) -> None:
    run = _completed_run(db_session)
    upsert_sms_opt_out(
        db_session,
        phone_number="415-555-0134",
        source="test",
        reason="blocked",
    )

    with pytest.raises(Exception) as exc_info:
        capture_notification_preference(
            db_session,
            run,
            NotificationPreferenceRequest(wants_sms=True, phone_number="415-555-0134"),
        )

    assert "permanent opt-out" in str(exc_info.value)
    status = get_sms_phone_status(db_session, "415-555-0134")
    assert status.valid is True
    assert status.phone_number_blocked is True


def test_twilio_provider_posts_to_messages_api(monkeypatch) -> None:
    settings = get_settings().model_copy(
        update={
            "twilio_account_sid": "AC123",
            "twilio_auth_token": "token",
            "twilio_from_number": "+15551230000",
        }
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return b'{"sid":"SM123","status":"queued"}'

    def fake_urlopen(http_request, timeout: int):
        captured["url"] = http_request.full_url
        captured["data"] = http_request.data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = send_sms(settings, to_phone_number="+14155550134", body="Done")

    assert result.provider_message_sid == "SM123"
    assert result.status == "queued"
    assert "AC123/Messages.json" in str(captured["url"])
    assert b"To=%2B14155550134" in captured["data"]


def test_twilio_provider_requires_config() -> None:
    settings = get_settings().model_copy(
        update={
            "twilio_account_sid": None,
            "twilio_auth_token": None,
            "twilio_from_number": None,
        }
    )

    with pytest.raises(TwilioConfigurationError):
        send_sms(settings, to_phone_number="+14155550134", body="Done")
