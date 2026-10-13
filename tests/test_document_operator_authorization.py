"""HTTP regression tests for platform document-job authorization."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.core.config import get_settings
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.models import Base
from app.database.auth_models import AppUser
from app.database.platform_auth_models import PlatformOperatorGrant
from app.main import create_app


ENDPOINTS = [
    "/api/documents/retry-failed",
    "/api/documents/tenders/999999/documents/refresh",
]


@pytest.fixture
def isolated_environment():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

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

    app = create_app(settings, session_factory=session_factory)

    assert app.state.owns_engine is False
    assert settings.auto_migrate is False

    try:
        yield app, session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def set_identity(app, subject):
    app.dependency_overrides[get_current_user] = lambda: (
        AuthenticatedIdentity(
            subject=subject,
            email="operator-regression@example.com",
            claims={"sub": subject, "role": "authenticated"},
        )
    )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unprovisioned_user_denied(isolated_environment, endpoint):
    app, _ = isolated_environment
    set_identity(app, str(uuid4()))

    response = TestClient(app).post(endpoint)

    assert response.status_code == 403


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_provisioned_user_without_grant_denied(
    isolated_environment, endpoint
):
    app, session_factory = isolated_environment
    subject = str(uuid4())

    with session_factory() as db:
        db.add(AppUser(supabase_user_id=subject))
        db.commit()

    set_identity(app, subject)

    response = TestClient(app).post(endpoint)

    assert response.status_code == 403


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_revoked_operator_denied(isolated_environment, endpoint):
    app, session_factory = isolated_environment
    subject = str(uuid4())

    with session_factory() as db:
        operator = AppUser(supabase_user_id=subject)
        administrator = AppUser(supabase_user_id=str(uuid4()))

        db.add_all([operator, administrator])
        db.flush()

        db.add(
            PlatformOperatorGrant(
                user_id=operator.id,
                permission="DOCUMENT_JOBS_MANAGE",
                status="REVOKED",
                granted_by_user_id=administrator.id,
                revoked_by_user_id=administrator.id,
                revoked_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    set_identity(app, subject)

    response = TestClient(app).post(endpoint)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "endpoint, expected_status",
    [
        ("/api/documents/retry-failed", 200),
        ("/api/documents/tenders/999999/documents/refresh", 404),
    ],
)
def test_active_operator_authorized(
    isolated_environment, endpoint, expected_status
):
    app, session_factory = isolated_environment
    subject = str(uuid4())

    with session_factory() as db:
        operator = AppUser(supabase_user_id=subject)
        administrator = AppUser(supabase_user_id=str(uuid4()))

        db.add_all([operator, administrator])
        db.flush()

        db.add(
            PlatformOperatorGrant(
                user_id=operator.id,
                permission="DOCUMENT_JOBS_MANAGE",
                status="ACTIVE",
                granted_by_user_id=administrator.id,
            )
        )
        db.commit()

    set_identity(app, subject)

    response = TestClient(app).post(endpoint)

    assert response.status_code == expected_status

    if expected_status == 200:
        assert response.json() == {"retried": 0}
    else:
        assert response.json()["detail"] == "Tender not found"
