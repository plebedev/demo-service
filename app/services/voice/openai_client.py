"""OpenAI Realtime Voice API client."""

from __future__ import annotations

from typing import Any

import websockets.asyncio.client

from app.services.voice.base_client import VoiceClient

_OPENAI_REALTIME_BASE = "wss://api.openai.com/v1/realtime"

# Maps the nested xAI/Twilio audio format type to OpenAI's flat format string.
_AUDIO_FORMAT_MAP: dict[str, str] = {
    "audio/pcmu": "g711_ulaw",
    "audio/pcma": "g711_alaw",
    "audio/pcm": "pcm16",
}


class OpenAiVoiceClient(VoiceClient):
    """OpenAI Realtime API voice client.

    Uses OpenAI's flat audio format fields and requires the OpenAI-Beta header.
    """

    async def _connect(self) -> None:
        url = f"{_OPENAI_REALTIME_BASE}?model={self._model}"
        self._ws = await websockets.asyncio.client.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
        )

    async def configure_session(
        self,
        instructions: str,
        tools: list[dict[str, Any]],
        voice: str = "alloy",
        audio_format: dict[str, Any] | None = None,
    ) -> None:
        """Send session.update using OpenAI's flat audio format fields."""
        audio_format = audio_format or {"type": "audio/pcm", "rate": 24000}
        flat_format = _AUDIO_FORMAT_MAP.get(
            audio_format.get("type", "audio/pcm"), "pcm16"
        )
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "voice": voice,
                    "instructions": instructions,
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.85,
                        "silence_duration_ms": 0,
                    },
                    "tools": tools,
                    "input_audio_format": flat_format,
                    "output_audio_format": flat_format,
                },
            }
        )
