"""Voice conversation cost estimation.

Rates are derived from published provider pricing docs and used to produce
a duration-based cost estimate.  Stored and displayed with an 'approximate'
disclaimer because:

  - xAI charges a flat $3.00/hour session rate regardless of audio direction.
  - OpenAI bills per audio token; without capturing the usage object from
    response.done events we approximate from wall-clock duration using the
    midpoint of the published $0.10–$0.35/min range for gpt-realtime-2.

TODO: For OpenAI, capture usage.input_audio_tokens / usage.output_audio_tokens
from the response.done WebSocket event to produce an exact token-based cost
instead of this duration-based approximation.
"""

from __future__ import annotations

# Per-second rates (USD).
_RATE_PER_SECOND: dict[str, float] = {
    "xai": 3.00 / 3600,  # $3.00/hr flat session rate
    "openai": 0.225 / 60,  # ~$0.225/min midpoint of $0.10–$0.35/min range
}


def estimate_cost(provider: str, total_seconds: float) -> float:
    """Return an estimated cost in USD for a voice session of the given duration.

    Args:
        provider: Lowercase provider id ('xai' or 'openai').
        total_seconds: Wall-clock duration of the conversation in seconds.

    Returns:
        Estimated cost in USD, rounded to 6 decimal places.
        Returns 0.0 for unknown providers.
    """
    rate = _RATE_PER_SECOND.get(provider.lower(), 0.0)
    return round(total_seconds * rate, 6)
