"""Minimal signed-token helpers for the invite-only phase-1 demo."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_hex

from fastapi import HTTPException, status

from app.core.config import Settings


@dataclass(frozen=True)
class AccessTokenClaims:
    """Parsed claims from a signed demo access token."""

    token_id: str
    invitation_code_id: int
    code: str
    issued_at: datetime
    expires_at: datetime


def _b64url_encode(raw: bytes) -> str:
    """Encode raw bytes as URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    """Decode a URL-safe base64 string that may omit padding."""
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}")


def _sign(payload_segment: str, secret: str) -> str:
    """Sign the payload segment with the configured HMAC secret."""
    digest = hmac.new(
        secret.encode("utf-8"), payload_segment.encode("ascii"), hashlib.sha256
    ).digest()
    return _b64url_encode(digest)


def create_access_token(
    *,
    settings: Settings,
    invitation_code_id: int,
    code: str,
    now: datetime | None = None,
) -> tuple[str, AccessTokenClaims]:
    """Create a signed access token and return both the token and parsed claims."""
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=settings.access_token_ttl_seconds)
    payload = {
        "jti": token_hex(16),
        "invitation_code_id": invitation_code_id,
        "code": code,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    payload_segment = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature_segment = _sign(payload_segment, settings.access_token_signing_key)
    token = f"{payload_segment}.{signature_segment}"

    return token, AccessTokenClaims(
        token_id=str(payload["jti"]),
        invitation_code_id=invitation_code_id,
        code=code,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def verify_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    """Validate a signed access token and return its claims."""
    try:
        payload_segment, signature_segment = token.split(".", maxsplit=1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        ) from exc

    expected_signature = _sign(payload_segment, settings.access_token_signing_key)
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )

    try:
        payload = json.loads(_b64url_decode(payload_segment))
        token_id = str(payload["jti"])
        invitation_code_id = int(payload["invitation_code_id"])
        code = str(payload["code"])
        issued_at = datetime.fromtimestamp(int(payload["iat"]), tz=UTC)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        ) from exc

    if expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token expired.",
        )

    return AccessTokenClaims(
        token_id=token_id,
        invitation_code_id=invitation_code_id,
        code=code,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def hash_ip_address(ip_address: str | None, settings: Settings) -> str | None:
    """Hash a client IP for coarse-grained redemption analytics."""
    if not ip_address:
        return None
    digest = hashlib.sha256(
        f"{settings.access_token_signing_key}:{ip_address}".encode("utf-8")
    ).hexdigest()
    return digest
