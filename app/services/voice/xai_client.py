"""xAI Realtime Voice API client."""

from __future__ import annotations

from typing import Any

import websockets.asyncio.client

from app.services.voice.base_client import VoiceClient

_XAI_REALTIME_BASE = "wss://api.x.ai/v1/realtime"


class XaiVoiceClient(VoiceClient):
    """xAI Voice Agent WebSocket client.

    Uses the nested audio format required by xAI's realtime API.
    """

    async def _connect(self) -> None:
        url = f"{_XAI_REALTIME_BASE}?model={self._model}"
        self._ws = await websockets.asyncio.client.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
            },
        )

    async def configure_session(
        self,
        instructions: str,
        tools: list[dict[str, Any]],
        voice: str = "eve",
        audio_format: dict[str, Any] | None = None,
    ) -> None:
        """Send session.update using xAI's nested audio format."""
        audio_format = audio_format or {"type": "audio/pcm", "rate": 24000}
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "voice": voice,
                    "instructions": instructions,
                    "input_audio_transcription": {"model": "grok-2-audio"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.85,
                        "silence_duration_ms": 0,
                    },
                    "tools": tools,
                    "audio": {
                        "input": {"format": audio_format},
                        "output": {"format": audio_format},
                    },
                },
            }
        )
