"""Local test sign-in for development only (DEV_LOGIN_ENABLED=true).

Lets a developer use the client portal on their own machine before Supabase is
set up. It is switched off by default, refused when APP_ENV=production, and only
answers requests that come from this computer (127.0.0.1 / ::1).

* ``POST /api/dev/login {"email": ...}`` issues a short-lived token signed with a
  random secret that exists only in this server process (a restart invalidates
  every dev token). No password is involved, which is why it must stay local.
* On first sign-in the user gets one demo seller profile (OWNER), so the portal
  has something to show. All normal authorization still applies afterwards.
* Supabase tokens keep working alongside it when SUPABASE_URL is configured.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_token_verifier
from app.api.deps import get_db
from app.api.seller_authorization import provision_app_user
from app.core.config import Settings
from app.core.supabase_auth import AuthenticatedIdentity

logger = logging.getLogger("app.api.dev_login")

DEV_ISSUER = "gem-local-dev-login"
DEV_AUDIENCE = "authenticated"
TOKEN_LIFETIME = timedelta(hours=8)
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_NAMESPACE = uuid.UUID("6f1d3c52-2a7e-4f0b-9a51-3d6c0e0b7a10")
_login_attempts: dict[str, list[datetime]] = {}
MAX_DEV_LOGIN_ATTEMPTS_PER_MIN = 30


class DevTokenVerifier:
    """Verifies dev tokens (HS256, per-process secret); hands anything else to Supabase."""

    def __init__(self, secret: bytes, fallback=None):
        self._secret = secret
        self._fallback = fallback

    def issue(self, email: str) -> tuple[str, int]:
        now = datetime.now(timezone.utc)
        claims = {
            "sub": str(uuid.uuid5(_NAMESPACE, email)),
            "email": email,
            "aud": DEV_AUDIENCE,
            "iss": DEV_ISSUER,
            "role": "authenticated",
            "iat": now,
            "exp": now + TOKEN_LIFETIME,
        }
        return jwt.encode(claims, self._secret, algorithm="HS256"), int(TOKEN_LIFETIME.total_seconds())

    def verify(self, token: str) -> AuthenticatedIdentity:
        if not token or not isinstance(token, str):
            raise ValueError("Missing access token")
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as exc:
            raise ValueError("Invalid authentication token") from exc
        if alg != "HS256":
            if self._fallback is None:
                raise ValueError("Invalid authentication token")
            return self._fallback().verify(token)
        try:
            claims = jwt.decode(token, self._secret, algorithms=["HS256"], audience=DEV_AUDIENCE,
                                issuer=DEV_ISSUER, options={"require": ["exp", "iat", "sub", "aud", "iss"]})
        except jwt.PyJWTError as exc:
            raise ValueError("Invalid authentication token") from exc
        return AuthenticatedIdentity(subject=claims["sub"], email=claims.get("email"), claims=claims)


class DevLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")


def _ensure_demo_seller(db: Session, user, email: str) -> None:
    from app.database.auth_models import SellerMembership
    from app.database.models import Seller, SellerRevision
    from app.eligibility.utils import calculate_seller_fingerprint

    # If the canonical Kosh demo seller exists, ensure the dev user has OWNER access to it.
    demo_seller = db.query(Seller).filter(Seller.name == "Meenakshi Precision Components").first()
    if demo_seller is not None:
        mem = db.query(SellerMembership).filter(
            SellerMembership.user_id == user.id,
            SellerMembership.seller_id == demo_seller.id,
        ).first()
        if mem is None:
            db.add(SellerMembership(user_id=user.id, seller_id=demo_seller.id, role="OWNER", status="ACTIVE"))
        # A populated local workspace may show a per-user verification notice.
        # This is not an OTP or evidence of approval; codes remain requester-only.
        from sqlalchemy import select
        from app.database.kosh_models import KoshOperationRecord, KoshActionIntent, KoshSandboxInbox
        ready=db.scalar(select(KoshOperationRecord.id).where(KoshOperationRecord.seller_id==demo_seller.id,
                        KoshOperationRecord.kind=="SETUP"))
        pending=db.scalar(select(KoshActionIntent).where(KoshActionIntent.seller_id==demo_seller.id,
                          KoshActionIntent.tier=="T3",KoshActionIntent.status=="PROPOSED")) if ready else None
        if pending:
            import json
            from app.actions.step_up import cipher
            notice=db.scalar(select(KoshSandboxInbox).where(KoshSandboxInbox.seller_id==demo_seller.id,
                             KoshSandboxInbox.recipient_user_id==user.id,KoshSandboxInbox.kind=="NOTICE"))
            if notice is None:
                notice=KoshSandboxInbox(id=str(uuid.uuid4()),seller_id=demo_seller.id,recipient_user_id=user.id,
                                        kind="NOTICE",intent_id=pending.id,encrypted_payload="")
                db.add(notice)
            notice.encrypted_payload=cipher().encrypt(json.dumps({"message":"A financing proposal awaits review. Request your own verification code before approving money or data sharing."}).encode()).decode()
        return

    if db.query(SellerMembership).filter(SellerMembership.user_id == user.id).first() is not None:
        return
    now = datetime.utcnow()
    seller = Seller(name=f"Demo seller ({email})", created_at=now, updated_at=now)
    db.add(seller)
    db.flush()
    db.add(SellerRevision(seller_id=seller.id, revision_number=1, is_active=True, created_at=now,
                          comment="Initial revision (local test sign-in)",
                          fingerprint=calculate_seller_fingerprint({"created_at": now.isoformat()})))
    db.add(SellerMembership(user_id=user.id, seller_id=seller.id, role="OWNER", status="ACTIVE"))


def install(app: FastAPI, settings: Settings) -> bool:
    """Wire the local test sign-in into ``app`` when enabled. Returns True if installed."""
    if not settings.dev_login_enabled:
        return False
    if settings.app_env.strip().lower() == "production":   # also rejected by assert_startup_safe
        raise ValueError("DEV_LOGIN_ENABLED must be false when APP_ENV=production")

    from app.api.auth import configured_supabase_url

    supabase_configured = bool(configured_supabase_url())
    verifier = DevTokenVerifier(secrets.token_bytes(32),
                                fallback=get_token_verifier if supabase_configured else None)
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    router = APIRouter(prefix="/api/dev", tags=["Local test sign-in (development only)"])

    @router.post("/login")
    def dev_login(body: DevLoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        host = request.client.host if request.client else ""
        if host not in LOCAL_HOSTS:
            raise HTTPException(status_code=403, detail="Local test sign-in only works from this computer")

        # In-memory attempt limiter
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=1)
        client_key = host or "local"
        recent = [t for t in _login_attempts.get(client_key, []) if t > cutoff]
        if len(recent) >= MAX_DEV_LOGIN_ATTEMPTS_PER_MIN:
            raise HTTPException(status_code=429, detail="Too many dev login attempts; try again later.")
        recent.append(now)
        _login_attempts[client_key] = recent

        email = body.email.strip().lower()
        token, expires_in = verifier.issue(email)
        identity = verifier.verify(token)
        user = provision_app_user(identity, db)
        _ensure_demo_seller(db, user, email)
        db.commit()
        logger.warning("dev_login user_id=%s (local test sign-in, not for production)", user.id)
        return {"access_token": token, "token_type": "bearer", "expires_in": expires_in, "email": email}

    app.include_router(router)
    logger.warning("Local test sign-in is ENABLED (DEV_LOGIN_ENABLED=true). Never use this in production.")
    return True
