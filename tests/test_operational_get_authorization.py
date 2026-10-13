"""Authorization regression tests for operational GET endpoints."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
    ("/api/extractions/jobs", "DOCUMENT_JOBS_MANAGE", 200),
    ("/api/extractions/jobs/999999", "DOCUMENT_JOBS_MANAGE", 404),
    ("/api/extractions/worker", "DOCUMENT_JOBS_MANAGE", 200),
    ("/api/tender-fields/jobs", "TENDER_FIELDS_MANAGE", 200),
    ("/api/tender-fields/jobs/999999", "TENDER_FIELDS_MANAGE", 404),
    ("/api/tender-fields/worker", "TENDER_FIELDS_MANAGE", 200),
    ("/api/ai-analysis/jobs", "AI_ANALYSIS_MANAGE", 200),
    ("/api/ai-analysis/jobs/999999", "AI_ANALYSIS_MANAGE", 404),
    ("/api/ai-analysis/worker", "AI_ANALYSIS_MANAGE", 200),
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
            email="operator-test@example.com",
            claims={"sub": subject, "role": "authenticated"},
        )
    )


@pytest.mark.parametrize("endpoint,permission,expected", ENDPOINTS)
@pytest.mark.parametrize("grant_status", ["MISSING", "REVOKED", "ACTIVE"])
def test_operator_access(
    isolated_environment, endpoint, permission, expected, grant_status
):
    app, factory = isolated_environment
    subject = str(uuid4())

    with factory() as db:
        operator = AppUser(supabase_user_id=subject)
        administrator = AppUser(supabase_user_id=str(uuid4()))

        db.add_all([operator, administrator])
        db.flush()

        if grant_status != "MISSING":
            grant = PlatformOperatorGrant(
                user_id=operator.id,
                permission=permission,
                status=grant_status,
                granted_by_user_id=administrator.id,
            )

            if grant_status == "REVOKED":
                grant.revoked_by_user_id = administrator.id
                grant.revoked_at = datetime.now(timezone.utc)

            db.add(grant)

        db.commit()

    set_identity(app, subject)

    response = TestClient(app).get(endpoint)

    if grant_status == "ACTIVE":
        assert response.status_code == expected
    else:
        assert response.status_code == 403
