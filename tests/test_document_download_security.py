"""Document download path-containment HTTP regression tests."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.core.config import get_settings
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.models import (
    Base,
    Tender,
    TenderDocument,
    DocumentVersion,
)
from app.main import create_app


@pytest.mark.parametrize(
    "case, expected_status",
    [
        ("valid", 200),
        ("parent", 403),
        ("sibling", 403),
    ],
)
def test_document_download_containment(
    tmp_path, case, expected_status
):
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

    storage = tmp_path / "documents"
    storage.mkdir()

    sibling = tmp_path / "documents-private"
    sibling.mkdir()

    (storage / "safe.txt").write_bytes(b"SAFE_DOCUMENT")
    (tmp_path / "outside.txt").write_bytes(b"PRIVATE_PARENT")
    (sibling / "secret.txt").write_bytes(b"PRIVATE_SIBLING")

    paths = {
        "valid": "safe.txt",
        "parent": "../outside.txt",
        "sibling": "../documents-private/secret.txt",
    }

    now = datetime.now(timezone.utc)

    try:
        with session_factory() as db:
            tender = Tender(
                id=1001,
                bid_number=f"TEST-{uuid4().hex[:12]}",
                first_seen_at=now,
                last_seen_at=now,
                source_fingerprint="test-download-security",
            )
            db.add(tender)
            db.flush()

            document = TenderDocument(
                id=2001,
                tender_id=tender.id,
                document_key="security-document",
                document_type="OTHER",
            )
            db.add(document)
            db.flush()

            version = DocumentVersion(
                id=3001,
                document_id=document.id,
                version_number=1,
                storage_path=paths[case],
                mime_type="text/plain",
            )
            db.add(version)
            db.commit()

        settings = get_settings().model_copy(
            update={
                "auto_migrate": False,
                "scheduler_enabled": False,
                "collect_on_startup": False,
                "document_worker_enabled": False,
                "extraction_worker_enabled": False,
                "field_extraction_worker_enabled": False,
                "ai_analysis_worker_enabled": False,
                "document_storage_path": str(storage),
            }
        )

        app = create_app(
            settings,
            session_factory=session_factory,
        )

        assert app.state.owns_engine is False
        assert settings.auto_migrate is False

        identity = AuthenticatedIdentity(
            subject=str(uuid4()),
            email="download-security@example.com",
            claims={"role": "authenticated"},
        )

        app.dependency_overrides[get_current_user] = (
            lambda: identity
        )
        app.dependency_overrides[get_settings] = (
            lambda: settings
        )

        try:
            client = TestClient(app)

            response = client.get(
                "/api/documents/2001/download-version/3001"
            )

            assert response.status_code == expected_status, (
                case,
                response.status_code,
                response.text,
            )

            if case == "valid":
                assert response.content == b"SAFE_DOCUMENT"
            else:
                assert b"PRIVATE_" not in response.content

        finally:
            app.dependency_overrides.clear()

    finally:
        engine.dispose()
