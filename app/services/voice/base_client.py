"""Abstract base class for realtime voice API clients (OpenAI-compatible protocol)."""

from __future__ import annotations

import abc
import json
import logging
from types import TracebackType
from typing import Any

import websockets
import websockets.asyncio.client

logger = logging.getLogger(__name__)


class VoiceClient(abc.ABC):
    """Manages one realtime voice WebSocket session.

    All providers share the same OpenAI-compatible wire protocol for audio
    streaming and tool calling. Subclasses only differ in how the WebSocket
    connection is opened and how session.update is formatted.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._ws: websockets.asyncio.client.ClientConnection | None = None

    # ---------------------------------------------------------------------------
    # Subclass interface
    # ---------------------------------------------------------------------------

    @abc.abstractmethod
    async def _connect(self) -> None:
        """Open self._ws with provider-specific URL and headers."""

    @abc.abstractmethod
    async def configure_session(
        self,
        instructions: str,
        tools: list[dict[str, Any]],
        voice: str,
        audio_format: dict[str, Any] | None = None,
    ) -> None:
        """Send session.update with provider-appropriate audio format."""

    # ---------------------------------------------------------------------------
    # Context manager
    # ---------------------------------------------------------------------------

    async def __aenter__(self) -> "VoiceClient":
        await self._connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._ws is not None:
            await self._ws.close()

    # ---------------------------------------------------------------------------
    # Protocol methods — identical across all providers
    # ---------------------------------------------------------------------------

    async def start_response(self) -> None:
        """Trigger the agent to generate its opening turn."""
        await self._send({"type": "response.create"})

    async def cancel_response(self) -> None:
        """Cancel the in-progress response (barge-in)."""
        await self._send({"type": "response.cancel"})

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
        """Receive and parse the next message from the provider."""
        assert self._ws is not None
        raw = await self._ws.recv()
        result: dict[str, Any] = json.loads(raw)
        return result

    async def _send(self, message: dict[str, Any]) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(message))
