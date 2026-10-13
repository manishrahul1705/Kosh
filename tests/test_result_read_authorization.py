"""Authorization tests for tender-analysis result GET endpoints (TENDER_ANALYSIS_READ)."""

import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user, get_token_verifier
from app.core.config import get_settings
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.auth_models import AppUser, SellerMembership
from app.database.models import Base, Seller
from app.database.platform_auth_models import PlatformOperatorGrant
from app.main import create_app


# Exact status the handler returns for an ACTIVE grant with placeholder IDs.
# 200 = list endpoint; 404 = handler looked up the placeholder ID and found nothing;
# 422 = handler validated the placeholder bid number and rejected its format.
ACTIVE_EXPECTED = {
    "/api/extractions": 200,
    "/api/extractions/document-version/999999": 404,
    "/api/extractions/999999": 404,
    "/api/extractions/999999/pages": 404,
    "/api/extractions/999999/pages/1": 404,
    "/api/extractions/999999/tables": 404,
    "/api/extractions/999999/sections": 404,
    "/api/tender-fields": 200,
    "/api/tender-fields/bid/GEM-TEST-BID": 422,
    "/api/tender-fields/extraction/999999": 404,
    "/api/tender-fields/999999": 404,
    "/api/tender-fields/999999/values": 404,
    "/api/tender-fields/999999/evidence": 404,
    "/api/tender-fields/999999/conflicts": 404,
    "/api/ai-analysis": 200,
    "/api/ai-analysis/bid/GEM-TEST-BID": 422,
    "/api/ai-analysis/stage3b/999999": 404,
    "/api/ai-analysis/999999": 404,
    "/api/ai-analysis/999999/requirements": 404,
    "/api/ai-analysis/999999/evidence": 404,
    "/api/ai-analysis/999999/flags": 404,
}


@pytest.fixture(autouse=True)
def supabase_settings(monkeypatch):
    """Provide a Supabase URL so the token verifier can be constructed.

    get_token_verifier() is cached and reads SUPABASE_URL from os.environ,
    so the cache is cleared before and after each test.
    """
    monkeypatch.setenv("SUPABASE_URL", "https://result-auth-tests.supabase.co")
    get_token_verifier.cache_clear()
    yield
    get_token_verifier.cache_clear()


READ = "TENDER_ANALYSIS_READ"

RESULT_ENDPOINTS = [
    "/api/extractions",
    "/api/extractions/document-version/999999",
    "/api/extractions/999999",
    "/api/extractions/999999/pages",
    "/api/extractions/999999/pages/1",
    "/api/extractions/999999/tables",
    "/api/extractions/999999/sections",
    "/api/tender-fields",
    "/api/tender-fields/bid/GEM-TEST-BID",
    "/api/tender-fields/extraction/999999",
    "/api/tender-fields/999999",
    "/api/tender-fields/999999/values",
    "/api/tender-fields/999999/evidence",
    "/api/tender-fields/999999/conflicts",
    "/api/ai-analysis",
    "/api/ai-analysis/bid/GEM-TEST-BID",
    "/api/ai-analysis/stage3b/999999",
    "/api/ai-analysis/999999",
    "/api/ai-analysis/999999/requirements",
    "/api/ai-analysis/999999/evidence",
    "/api/ai-analysis/999999/flags",
]

OTHER_GRANTS = [
    ("TENDER_FIELDS_MANAGE", "ACTIVE"),
    ("AI_ANALYSIS_MANAGE", "ACTIVE"),
    ("DOCUMENT_JOBS_MANAGE", "ACTIVE"),
    ("COLLECTION_RUN_MANAGE", "ACTIVE"),
]


@pytest.fixture
def isolated_environment():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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

    try:
        yield app, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def set_identity(app, subject):
    app.dependency_overrides[get_current_user] = lambda: (
        AuthenticatedIdentity(
            subject=subject,
            email="result-test@example.com",
            claims={"sub": subject, "role": "authenticated"},
        )
    )


def seed_user(factory, subject, grants):
    """Create a provisioned user with the given (permission, status) grants."""
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

        db.commit()


def template_matches(template, endpoint):
    """True when an OpenAPI path template (e.g. /x/{id}) matches a concrete endpoint."""
    parts = re.split(r"(\{[^}]+\})", template)
    pattern = "".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts)
    return re.fullmatch(pattern, endpoint) is not None


def test_endpoint_list_is_complete():
    assert len(RESULT_ENDPOINTS) == 21
    assert len(set(RESULT_ENDPOINTS)) == 21


@pytest.mark.parametrize("endpoint", RESULT_ENDPOINTS)
def test_anonymous_request_is_rejected(isolated_environment, endpoint):
    app, _ = isolated_environment

    response = TestClient(app).get(endpoint)

    assert response.status_code == 401


@pytest.mark.parametrize("endpoint", RESULT_ENDPOINTS)
def test_unprovisioned_user_is_denied(isolated_environment, endpoint):
    app, _ = isolated_environment
    set_identity(app, str(uuid4()))

    response = TestClient(app).get(endpoint)

    assert response.status_code == 403


@pytest.mark.parametrize("endpoint", RESULT_ENDPOINTS)
@pytest.mark.parametrize(
    "scenario, grants",
    [
        ("NO_GRANT", []),
        ("REVOKED", [(READ, "REVOKED")]),
        ("OTHER_PERMISSIONS_ONLY", OTHER_GRANTS),
    ],
)
def test_missing_revoked_or_unrelated_grant_is_forbidden(
    isolated_environment, endpoint, scenario, grants
):
    app, factory = isolated_environment
    subject = str(uuid4())
    seed_user(factory, subject, grants)
    set_identity(app, subject)

    response = TestClient(app).get(endpoint)

    assert response.status_code == 403, scenario


@pytest.mark.parametrize("endpoint", RESULT_ENDPOINTS)
def test_active_read_grant_reaches_endpoint(isolated_environment, endpoint):
    app, factory = isolated_environment
    subject = str(uuid4())
    seed_user(factory, subject, [(READ, "ACTIVE")])
    set_identity(app, subject)

    response = TestClient(app).get(endpoint)

    assert response.status_code == ACTIVE_EXPECTED[endpoint], response.text


def test_openapi_declares_security_for_every_result_endpoint(isolated_environment):
    app, _ = isolated_environment
    paths = app.openapi()["paths"]

    for endpoint in RESULT_ENDPOINTS:
        matches = [t for t in paths if template_matches(t, endpoint)]
        assert len(matches) == 1, f"{endpoint} matched {matches}"
        operation = paths[matches[0]].get("get", {})
        assert operation.get("security"), f"{matches[0]} has no security declaration"


def seed_seller_member(factory, subject, role, status="ACTIVE"):
    # Provisioned user whose only access is a seller membership; no platform grants.
    with factory() as db:
        seller = Seller(name="Result Isolation Seller " + uuid4().hex[:8])
        user = AppUser(supabase_user_id=subject)
        db.add_all([seller, user])
        db.flush()
        db.add(SellerMembership(user_id=user.id, seller_id=seller.id, role=role, status=status))
        db.commit()


@pytest.mark.parametrize("endpoint", RESULT_ENDPOINTS)
@pytest.mark.parametrize("role", ["OWNER", "ADMIN", "EDITOR", "VIEWER", "APPROVER"])
def test_seller_membership_alone_does_not_grant_result_access(
    isolated_environment, endpoint, role
):
    app, factory = isolated_environment
    subject = str(uuid4())
    seed_seller_member(factory, subject, role)
    set_identity(app, subject)

    response = TestClient(app).get(endpoint)

    assert response.status_code == 403, response.text
    assert "Platform operator access denied" in response.text


@pytest.mark.parametrize("endpoint", RESULT_ENDPOINTS)
def test_pending_seller_membership_does_not_grant_result_access(
    isolated_environment, endpoint
):
    app, factory = isolated_environment
    subject = str(uuid4())
    seed_seller_member(factory, subject, "OWNER", status="PENDING")
    set_identity(app, subject)

    response = TestClient(app).get(endpoint)

    assert response.status_code == 403, response.text
