"""Verify Supabase Auth access tokens using public JWKS keys."""

from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Verified Supabase user identity."""

    subject: str
    email: str | None
    claims: dict[str, Any]


class SupabaseTokenVerifier:
    """Verify Supabase access tokens without privileged API keys."""

    def __init__(self, project_url: str):
        project_url = project_url.rstrip("/")

        if not project_url.startswith("https://"):
            raise ValueError("Supabase project URL must use HTTPS")

        self.issuer = f"{project_url}/auth/v1"
        self.jwks_url = (
            f"{self.issuer}/.well-known/jwks.json"
        )
        self.client = PyJWKClient(
            self.jwks_url,
            cache_jwk_set=True,
            lifespan=300,
            timeout=10,
        )

    def verify(self, token: str) -> AuthenticatedIdentity:
        """Validate signature, issuer, audience and token lifetime."""

        if not token or not isinstance(token, str):
            raise ValueError("Missing access token")

        try:
            signing_key = self.client.get_signing_key_from_jwt(token)

            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
                issuer=self.issuer,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "sub",
                        "aud",
                        "iss",
                    ]
                },
                leeway=30,
            )

        except (PyJWTError, ValueError, OSError) as exc:
            raise ValueError("Invalid authentication token") from exc

        role = claims.get("role")
        if role != "authenticated":
            raise ValueError("Token does not represent an authenticated user")

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("Invalid token subject")

        email = claims.get("email")
        if not isinstance(email, str):
            email = None

        return AuthenticatedIdentity(
            subject=subject,
            email=email,
            claims=claims,
        )
