"""End-to-end auth tests: real JWT verification and real get_current_user.

Only get_token_verifier is overridden, to supply a locally generated P-256 public key.
Nothing touches the network, a running server, or data/gem.db. The database is in-memory
SQLite, and TestClient is used without a context manager so the app lifespan
(startup recovery and migrations) never runs.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user, get_token_verifier
from app.core.config import get_settings
from app.core.supabase_auth import SupabaseTokenVerifier
from app.database.auth_models import AppUser, SellerMembership
from app.database.models import Base, Seller
from app.database.platform_auth_models import PlatformOperatorGrant
from app.main import create_app


READ = "TENDER_ANALYSIS_READ"
ENDPOINT = "/api/extractions"


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    settings = get_settings().model_copy(
        update={
            "auto_migrate": False,
            "scheduler_enabled": False,
            "collect_on_startup": False,
            "document_worker_enabled": False,
            "extraction_worker_enabled": False,
            "field_extraction_worker_enabled": False,
            "ai_analysis_worker_enabled": False,
        }
    )
    app = create_app(settings, session_factory=factory)

    private_key = ec.generate_private_key(ec.SECP256R1())
    verifier = SupabaseTokenVerifier("https://offline-auth-tests.supabase.co")
    signing = SimpleNamespace(key=private_key.public_key())
    verifier.client.get_signing_key_from_jwt = lambda token: signing
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    try:
        yield app, factory, private_key, verifier
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def claims_for(verifier, subject, **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "role": "authenticated",
        "aud": "authenticated",
        "iss": verifier.issuer,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    claims.update(overrides)
    return claims


def bearer(claims, key):
    token = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "test-key"})
    return {"Authorization": f"Bearer {token}"}


def seed(factory, subject, grants=(), seller_role=None):
    with factory() as db:
        user = AppUser(supabase_user_id=subject)
        admin = AppUser(supabase_user_id=str(uuid4()))
        db.add_all([user, admin])
        db.flush()
        for permission, status in grants:
            grant = PlatformOperatorGrant(
                user_id=user.id,
                permission=permission,
                status=status,
                granted_by_user_id=admin.id,
            )
            if status == "REVOKED":
                grant.revoked_by_user_id = admin.id
                grant.revoked_at = datetime.now(timezone.utc)
            db.add(grant)
        if seller_role:
            seller = Seller(name="Offline Auth Seller " + uuid4().hex[:8])
            db.add(seller)
            db.flush()
            db.add(
                SellerMembership(
                    user_id=user.id,
                    seller_id=seller.id,
                    role=seller_role,
                    status="ACTIVE",
                )
            )
        db.commit()


def test_real_get_current_user_is_in_use(env):
    app, *_ = env
    assert get_current_user not in app.dependency_overrides


def test_no_token_is_401(env):
    app, *_ = env
    assert TestClient(app).get(ENDPOINT).status_code == 401


def test_expired_token_is_401(env):
    app, factory, key, verifier = env
    subject = str(uuid4())
    seed(factory, subject, [(READ, "ACTIVE")])
    claims = claims_for(
        verifier, subject, exp=datetime.now(timezone.utc) - timedelta(minutes=5)
    )
    response = TestClient(app).get(ENDPOINT, headers=bearer(claims, key))
    assert response.status_code == 401


def test_token_signed_by_other_key_is_401(env):
    app, factory, _key, verifier = env
    subject = str(uuid4())
    seed(factory, subject, [(READ, "ACTIVE")])
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    claims = claims_for(verifier, subject)
    response = TestClient(app).get(ENDPOINT, headers=bearer(claims, attacker_key))
    assert response.status_code == 401


@pytest.mark.parametrize(
    "override",
    [{"aud": "anon"}, {"iss": "https://evil.example/auth/v1"}],
    ids=["wrong_audience", "wrong_issuer"],
)
def test_wrong_audience_or_issuer_is_401(env, override):
    app, factory, key, verifier = env
    subject = str(uuid4())
    seed(factory, subject, [(READ, "ACTIVE")])
    claims = claims_for(verifier, subject, **override)
    response = TestClient(app).get(ENDPOINT, headers=bearer(claims, key))
    assert response.status_code == 401


def test_valid_token_without_app_user_is_403(env):
    app, _factory, key, verifier = env
    claims = claims_for(verifier, str(uuid4()))
    response = TestClient(app).get(ENDPOINT, headers=bearer(claims, key))
    assert response.status_code == 403


@pytest.mark.parametrize(
    "grants",
    [
        [],
        [(READ, "REVOKED")],
        [("TENDER_FIELDS_MANAGE", "ACTIVE"), ("AI_ANALYSIS_MANAGE", "ACTIVE")],
    ],
    ids=["no_grant", "revoked_read", "unrelated_grants"],
)
def test_provisioned_user_without_active_read_grant_is_403(env, grants):
    app, factory, key, verifier = env
    subject = str(uuid4())
    seed(factory, subject, grants)
    claims = claims_for(verifier, subject)
    response = TestClient(app).get(ENDPOINT, headers=bearer(claims, key))
    assert response.status_code == 403


def test_seller_membership_alone_is_403(env):
    app, factory, key, verifier = env
    subject = str(uuid4())
    seed(factory, subject, seller_role="OWNER")
    claims = claims_for(verifier, subject)
    response = TestClient(app).get(ENDPOINT, headers=bearer(claims, key))
    assert response.status_code == 403


def test_valid_token_with_active_read_grant_reaches_endpoint(env):
    app, factory, key, verifier = env
    subject = str(uuid4())
    seed(factory, subject, [(READ, "ACTIVE")])
    claims = claims_for(verifier, subject)
    response = TestClient(app).get(ENDPOINT, headers=bearer(claims, key))
    assert response.status_code == 200, response.text
