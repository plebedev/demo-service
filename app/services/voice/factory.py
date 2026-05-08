"""Factory for creating the configured voice client."""

from __future__ import annotations

from app.core.config import Settings
from app.services.voice.base_client import VoiceClient

# One realtime audio model per provider — not user-configurable.
_PROVIDER_MODELS: dict[str, str] = {
    "xai": "grok-voice-think-fast-1.0",
    "openai": "gpt-realtime-1.5",
}


def get_voice_client(settings: Settings, provider: str | None = None) -> VoiceClient:
    """Return the configured realtime voice client.

    The provider is resolved from the optional override first, then the global
    VOICE_PROVIDER setting. Models are hardcoded per provider.
    """
    provider = (provider or settings.voice_provider).lower()

    if provider not in _PROVIDER_MODELS:
        raise ValueError(
            f"Unknown VOICE_PROVIDER: {provider!r}. "
            f"Valid values: {sorted(_PROVIDER_MODELS)}"
        )

    model = _PROVIDER_MODELS[provider]

    if provider == "openai":
        from app.services.voice.openai_client import OpenAiVoiceClient

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when VOICE_PROVIDER=openai")
        return OpenAiVoiceClient(api_key=settings.openai_api_key, model=model)

    # provider == "xai"
    from app.services.voice.xai_client import XaiVoiceClient

    if not settings.xai_api_key:
        raise RuntimeError("XAI_API_KEY is required when VOICE_PROVIDER=xai")
    return XaiVoiceClient(api_key=settings.xai_api_key, model=model)
