"""FastAPI dependency for Supabase-authenticated identities."""

from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.supabase_auth import (
    AuthenticatedIdentity,
    SupabaseTokenVerifier,
)


security = HTTPBearer(auto_error=False)


PLACEHOLDER_MARKERS = ("your-project",)


def configured_supabase_url() -> str:
    """SUPABASE_URL from the process environment, else from .env (via Settings).

    The .env.example placeholder counts as "not configured"."""
    import os

    project_url = os.environ.get("SUPABASE_URL", "").strip()
    if not project_url:
        from app.core.config import get_settings

        project_url = (get_settings().supabase_url or "").strip()
    if any(marker in project_url for marker in PLACEHOLDER_MARKERS):
        return ""
    return project_url


@lru_cache(maxsize=1)
def get_token_verifier() -> SupabaseTokenVerifier:
    """Return the configured public-key JWT verifier."""

    project_url = configured_supabase_url()

    if not project_url:
        # Fail closed with a controlled 503 instead of an unhandled 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )

    return SupabaseTokenVerifier(project_url)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    verifier: SupabaseTokenVerifier = Depends(get_token_verifier),
) -> AuthenticatedIdentity:
    """Require a valid Supabase authenticated-user access token."""

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        return verifier.verify(credentials.credentials)
    except ValueError:
        raise unauthorized from None
