"""Integration status helpers used by system status endpoints."""

from app.core.config import Settings
from app.schemas.status import ProviderStatus, ProviderStatuses


def provider_statuses(settings: Settings) -> ProviderStatuses:
    """Build provider readiness flags from the current settings."""
    return ProviderStatuses(
        twilio=ProviderStatus(
            configured=bool(
                settings.twilio_account_sid
                and settings.twilio_auth_token
                and settings.twilio_from_number
            )
        ),
        plivo=ProviderStatus(
            configured=bool(settings.plivo_auth_id and settings.plivo_auth_token)
        ),
        openai=ProviderStatus(configured=bool(settings.openai_api_key)),
        anthropic=ProviderStatus(configured=bool(settings.anthropic_api_key)),
    )


def feature_statuses(settings: Settings) -> dict[str, bool]:
    """Build feature availability flags for UI capability gating."""
    return {"SmsNotification": settings.sms_notification_enabled}
