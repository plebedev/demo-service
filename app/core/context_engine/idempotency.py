"""Idempotency helpers for Context Engine ingestion."""

from __future__ import annotations

import hashlib
import json

MAX_IDEMPOTENCY_KEY_LENGTH = 255


def normalize_idempotency_key(value: str) -> str:
    """Return a trimmed idempotency key or raise when it is unusable."""
    key = value.strip()
    if not key or len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError(
            "Idempotency-Key must be between 1 and "
            f"{MAX_IDEMPOTENCY_KEY_LENGTH} characters."
        )
    return key


def request_fingerprint(payload: object) -> str:
    """Return a stable SHA-256 fingerprint for a JSON-compatible payload.

    Mapping key order and insignificant whitespace do not affect the result, so
    semantically equivalent payloads share one fingerprint.
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
