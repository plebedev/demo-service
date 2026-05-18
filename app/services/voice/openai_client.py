"""OpenAI Realtime Voice API client."""

from __future__ import annotations

import base64
import struct
from typing import Any

import websockets.asyncio.client

from app.services.voice.base_client import VoiceClient

# OpenAI uses slightly different event type names for audio output than xAI.
# Normalize them here so _handle_xai_to_twilio stays provider-agnostic.
_OPENAI_EVENT_REMAP: dict[str, str] = {
    "response.audio.delta": "response.output_audio.delta",
    "response.audio_transcript.delta": "response.output_audio_transcript.delta",
    "response.audio_transcript.done": "response.output_audio_transcript.done",
}

_OPENAI_REALTIME_BASE = "wss://api.openai.com/v1/realtime"


class OpenAiVoiceClient(VoiceClient):
    """OpenAI Realtime API voice client.

    Uses OpenAI's GA Realtime session shape.
    """

    async def _connect(self) -> None:
        url = f"{_OPENAI_REALTIME_BASE}?model={self._model}"
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
        voice: str = "alloy",
        audio_format: dict[str, Any] | None = None,
    ) -> None:
        """Send session.update using OpenAI's GA nested audio format fields."""
        del audio_format
        openai_audio_format = {"type": "audio/pcm", "rate": 24000}
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "model": self._model,
                    "instructions": (
                        f"{instructions}\n\nRespond only in English unless the user "
                        "explicitly asks for another language."
                    ),
                    "output_modalities": ["audio"],
                    "tools": tools,
                    "audio": {
                        "input": {
                            "format": openai_audio_format,
                            "transcription": {
                                "model": "gpt-4o-mini-transcribe",
                                "language": "en",
                            },
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.85,
                                "silence_duration_ms": 0,
                            },
                        },
                        "output": {
                            "format": openai_audio_format,
                            "voice": voice,
                        },
                    },
                },
            }
        )

    async def send_audio(self, audio_b64: str) -> None:
        """Convert bridge μ-law audio to OpenAI PCM16/24k before appending."""
        await self._send(
            {
                "type": "input_audio_buffer.append",
                "audio": _mulaw_8khz_b64_to_pcm16_24khz_b64(audio_b64),
            }
        )

    async def receive(self) -> dict[str, Any]:
        """Receive next event, remapping OpenAI audio event names to xAI-style names."""
        event = await super().receive()
        remapped = _OPENAI_EVENT_REMAP.get(event.get("type", ""))
        if remapped:
            event = {**event, "type": remapped}
        if event.get("type") == "response.output_audio.delta" and event.get("delta"):
            return {
                **event,
                "delta": _pcm16_24khz_b64_to_mulaw_8khz_b64(str(event["delta"])),
            }
        return event


def _mulaw_8khz_b64_to_pcm16_24khz_b64(audio_b64: str) -> str:
    """Decode 8 kHz G.711 μ-law and upsample to OpenAI PCM16/24k."""
    mulaw = base64.b64decode(audio_b64)
    pcm8 = [_decode_mulaw_sample(byte) for byte in mulaw]
    pcm24 = _resample_pcm16(pcm8, source_rate=8000, target_rate=24000)
    return _pcm16_samples_to_b64(pcm24)


def _pcm16_24khz_b64_to_mulaw_8khz_b64(audio_b64: str) -> str:
    """Downsample OpenAI PCM16/24k output and encode as 8 kHz μ-law."""
    raw = base64.b64decode(audio_b64)
    if len(raw) % 2 != 0:
        raw = raw[:-1]
    if not raw:
        return ""
    pcm24 = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    pcm8 = _resample_pcm16(pcm24, source_rate=24000, target_rate=8000)
    mulaw = bytes(_encode_mulaw_sample(sample) for sample in pcm8)
    return base64.b64encode(mulaw).decode("ascii")


def _pcm16_samples_to_b64(samples: list[int]) -> str:
    if not samples:
        return ""
    raw = struct.pack(f"<{len(samples)}h", *samples)
    return base64.b64encode(raw).decode("ascii")


def _resample_pcm16(
    samples: list[int],
    *,
    source_rate: int,
    target_rate: int,
) -> list[int]:
    """Linear-resample mono PCM16 samples between the bridge and OpenAI rates."""
    if not samples:
        return []
    if source_rate == target_rate:
        return samples

    output_length = max(1, round(len(samples) * target_rate / source_rate))
    ratio = source_rate / target_rate
    output: list[int] = []
    for out_index in range(output_length):
        source_pos = out_index * ratio
        left_index = int(source_pos)
        right_index = min(left_index + 1, len(samples) - 1)
        fraction = source_pos - left_index
        interpolated = (
            samples[left_index] * (1 - fraction) + samples[right_index] * fraction
        )
        output.append(_clamp_pcm16(round(interpolated)))
    return output


def _decode_mulaw_sample(byte: int) -> int:
    """Decode one bridge μ-law byte to linear PCM16.

    This intentionally mirrors the browser helper in voice-demo-workspace.tsx.
    """
    value = (~byte) & 0xFF
    sign = value & 0x80
    exponent = (value >> 4) & 0x07
    mantissa = value & 0x0F
    sample = ((mantissa | 0x10) << (exponent + 3)) - 33
    return -sample if sign else sample


def _encode_mulaw_sample(sample: int) -> int:
    """Encode one PCM16 sample as bridge μ-law.

    This intentionally mirrors the browser helper in voice-demo-workspace.tsx.
    """
    bias = 33
    clip = 32635
    sample = _clamp_pcm16(sample)
    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    if sample > clip:
        sample = clip
    sample += bias
    exponent = 7
    mask = 0x4000
    while (sample & mask) == 0 and exponent > 0:
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa)) & 0xFF


def _clamp_pcm16(value: int) -> int:
    return max(-32768, min(32767, value))
