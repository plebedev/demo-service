"""Reusable request dependencies for access tokens and internal admin auth."""

from __future__ import annotations

from collections.abc import Callable
import hmac

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.experiences import ExperienceId
from app.core.security import AccessTokenClaims, verify_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AccessTokenClaims:
    """Require and validate the phase-1 signed access token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token required.",
        )
    return verify_access_token(credentials.credentials, settings)


def require_experience_access(
    experience_id: ExperienceId,
) -> Callable[..., AccessTokenClaims]:
    """Build a dependency requiring a token scoped to one demo experience."""

    def dependency(
        claims: AccessTokenClaims = Depends(get_current_access_token),
    ) -> AccessTokenClaims:
        if claims.experience_id != experience_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access token is not valid for this experience.",
            )
        return claims

    return dependency


def require_admin_secret(
    x_admin_secret: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Protect internal admin endpoints with a shared secret header."""
    if not x_admin_secret or not hmac.compare_digest(
        x_admin_secret, settings.admin_api_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin secret.",
        )
