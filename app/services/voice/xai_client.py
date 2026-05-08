"""xAI Realtime Voice API client for bidirectional audio streaming."""

from __future__ import annotations

import json
import logging
from types import TracebackType
from typing import Any

import websockets
import websockets.asyncio.client

logger = logging.getLogger(__name__)

_XAI_REALTIME_BASE = "wss://api.x.ai/v1/realtime"


class XaiVoiceClient:
    """Manages one xAI Voice Agent WebSocket session."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._ws: websockets.asyncio.client.ClientConnection | None = None

    async def __aenter__(self) -> "XaiVoiceClient":
        url = f"{_XAI_REALTIME_BASE}?model={self._model}"
        self._ws = await websockets.asyncio.client.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def configure_session(
        self,
        instructions: str,
        tools: list[dict[str, Any]],
        voice: str = "Eve",
        sample_rate: int = 24000,
    ) -> None:
        """Send session.update to configure the voice agent."""
        audio_format = {"type": "audio/pcm", "rate": sample_rate}
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

    async def start_response(self) -> None:
        """Trigger the agent to generate its opening turn."""
        await self._send({"type": "response.create"})

    async def send_audio(self, audio_b64: str) -> None:
        """Append a base64-encoded audio chunk to the input buffer."""
        await self._send({"type": "input_audio_buffer.append", "audio": audio_b64})

    async def send_tool_result(self, call_id: str, output: str) -> None:
        """Submit a tool call result and trigger the next response."""
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            }
        )
        await self._send({"type": "response.create"})

    async def receive(self) -> dict[str, Any]:
        """Receive and parse the next message from xAI."""
        assert self._ws is not None
        raw = await self._ws.recv()
        result: dict[str, Any] = json.loads(raw)
        return result

    async def _send(self, message: dict[str, Any]) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(message))
