"""HTTP authorization tests for seller-scoped eligibility APIs."""

from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.auth_models import AppUser, SellerMembership
from app.database.models import EligibilityRun, Seller, SellerRevision, Tender
from app.main import create_app


@pytest.fixture
def security_setup(settings, session_factory, source, monkeypatch):
    monkeypatch.setenv(
        "SUPABASE_URL",
        "https://auth-security-tests.supabase.co",
    )
    """Use the existing disposable migrated SQLite database."""
    owner_subject = str(uuid4())
    viewer_subject = str(uuid4())
    outsider_subject = str(uuid4())
    editor_subject = str(uuid4())

    with session_factory() as db:
        seller_a = Seller(name="Authorization Test Seller A")
        seller_b = Seller(name="Authorization Test Seller B")
        db.add_all([seller_a, seller_b])
        db.flush()

        revision_a = SellerRevision(
            seller_id=seller_a.id,
            revision_number=1,
            fingerprint="a" * 64,
        )
        revision_b = SellerRevision(
            seller_id=seller_b.id,
            revision_number=1,
            fingerprint="b" * 64,
        )
        db.add_all([revision_a, revision_b])
        db.flush()

        owner = AppUser(supabase_user_id=owner_subject)
        viewer = AppUser(supabase_user_id=viewer_subject)
        outsider = AppUser(supabase_user_id=outsider_subject)
        editor = AppUser(supabase_user_id=editor_subject)
        db.add_all([owner, viewer, outsider, editor])
        db.flush()

        db.add_all([
            SellerMembership(
                user_id=owner.id,
                seller_id=seller_a.id,
                role="OWNER",
                status="ACTIVE",
            ),
            SellerMembership(
                user_id=viewer.id,
                seller_id=seller_a.id,
                role="VIEWER",
                status="ACTIVE",
            ),
        ])

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        tender_a = Tender(
            id=10001,
            bid_number="AUTH-TEST-10001",
            title="Authorization Test Tender A",
            first_seen_at=now,
            last_seen_at=now,
            source_fingerprint="a" * 64,
        )
        tender_b = Tender(
            id=10002,
            bid_number="AUTH-TEST-10002",
            title="Authorization Test Tender B",
            first_seen_at=now,
            last_seen_at=now,
            source_fingerprint="b" * 64,
        )

        db.add(SellerMembership(
            user_id=editor.id,
            seller_id=seller_a.id,
            role="EDITOR",
            status="ACTIVE",
        ))

        db.add_all([tender_a, tender_b])
        db.flush()

        run_a = EligibilityRun(
            tender_id=10001,
            seller_id=seller_a.id,
            seller_revision_id=revision_a.id,
            corpus_fingerprint="a" * 64,
            engine_version="security-test",
            status="REVIEW_REQUIRED",
            ai_state_fingerprint="a" * 64,
        )
        run_b = EligibilityRun(
            tender_id=10002,
            seller_id=seller_b.id,
            seller_revision_id=revision_b.id,
            corpus_fingerprint="b" * 64,
            engine_version="security-test",
            status="REVIEW_REQUIRED",
            ai_state_fingerprint="b" * 64,
        )
        db.add_all([run_a, run_b])
        db.commit()

        ids = {
            "seller_a": seller_a.id,
            "seller_b": seller_b.id,
            "run_a": run_a.id,
            "run_b": run_b.id,
        }

    app = create_app(
        settings,
        session_factory=session_factory,
        collector_factory=source,
    )

    def identity_for(subject):
        return AuthenticatedIdentity(
            subject=subject,
            email=None,
            claims={"sub": subject, "role": "authenticated"},
        )

    with TestClient(app) as client:
        yield {
            "client": client,
            "app": app,
            "ids": ids,
            "identities": {
                "owner": identity_for(owner_subject),
                "viewer": identity_for(viewer_subject),
                "outsider": identity_for(outsider_subject),
                "editor": identity_for(editor_subject),
            },
        }

    app.dependency_overrides.clear()


def request_as(setup, role, method, path, **kwargs):
    app = setup["app"]

    app.dependency_overrides[get_current_user] = (
        lambda: setup["identities"][role]
    )

    try:
        return setup["client"].request(method, path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_owner_lists_only_own_seller_runs(security_setup):
    response = request_as(
        security_setup, "owner", "GET", "/api/eligibility"
    )
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [
        security_setup["ids"]["run_a"]
    ]


def test_owner_can_read_own_run(security_setup):
    run_id = security_setup["ids"]["run_a"]
    response = request_as(
        security_setup, "owner", "GET", f"/api/eligibility/{run_id}"
    )
    assert response.status_code == 200, response.text


def test_owner_cannot_read_other_seller_run(security_setup):
    run_id = security_setup["ids"]["run_b"]
    response = request_as(
        security_setup, "owner", "GET", f"/api/eligibility/{run_id}"
    )
    assert response.status_code == 403, response.text


def test_owner_cannot_filter_by_other_seller(security_setup):
    seller_id = security_setup["ids"]["seller_b"]
    response = request_as(
        security_setup,
        "owner",
        "GET",
        "/api/eligibility",
        params={"seller_id": seller_id},
    )
    assert response.status_code == 403, response.text


def test_viewer_can_read_own_seller_run(security_setup):
    run_id = security_setup["ids"]["run_a"]
    response = request_as(
        security_setup, "viewer", "GET", f"/api/eligibility/{run_id}"
    )
    assert response.status_code == 200, response.text


def test_viewer_cannot_evaluate(security_setup):
    response = request_as(
        security_setup,
        "viewer",
        "POST",
        "/api/eligibility/evaluate",
        json={
            "tender_id": 10001,
            "seller_id": security_setup["ids"]["seller_a"],
        },
    )
    assert response.status_code == 403, response.text


def test_outsider_cannot_read_run(security_setup):
    run_id = security_setup["ids"]["run_a"]
    response = request_as(
        security_setup, "outsider", "GET", f"/api/eligibility/{run_id}"
    )
    assert response.status_code == 403, response.text


def test_outsider_cannot_evaluate(security_setup):
    response = request_as(
        security_setup,
        "outsider",
        "POST",
        "/api/eligibility/evaluate",
        json={
            "tender_id": 10001,
            "seller_id": security_setup["ids"]["seller_a"],
        },
    )
    assert response.status_code == 403, response.text


def test_nonexistent_run_returns_404(security_setup):
    response = request_as(
        security_setup,
        "owner",
        "GET",
        "/api/eligibility/999999999",
    )
    assert response.status_code == 404, response.text


def test_missing_token_list_rejected(security_setup):
    response = security_setup["client"].get("/api/eligibility")
    assert response.status_code == 401


def test_missing_token_detail_rejected(security_setup):
    run_id = security_setup["ids"]["run_a"]
    response = security_setup["client"].get(
        f"/api/eligibility/{run_id}"
    )
    assert response.status_code == 401


def test_missing_token_evaluate_rejected(security_setup):
    response = security_setup["client"].post(
        "/api/eligibility/evaluate",
        json={
            "tender_id": 10001,
            "seller_id": security_setup["ids"]["seller_a"],
        },
    )
    assert response.status_code == 401


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_authorized_role_can_initiate_evaluation(
    security_setup, role
):
    setup = security_setup
    ids = setup["ids"]

    from app.database.models import EligibilityRun
    from app.api.deps import get_db

    with patch(
        "app.api.eligibility.EligibilityService.evaluate_tender"
    ) as evaluate:
        def return_existing_run(tender_id, seller_id):
            assert tender_id == 10001
            assert seller_id == ids["seller_a"]
            with setup["app"].state.session_factory() as db:
                run = db.get(EligibilityRun, ids["run_a"])
                db.expunge(run)
                return run

        evaluate.side_effect = return_existing_run

        response = request_as(
            setup,
            role,
            "POST",
            "/api/eligibility/evaluate",
            json={
                "tender_id": 10001,
                "seller_id": ids["seller_a"],
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["seller_id"] == ids["seller_a"]
    evaluate.assert_called_once_with(
        10001, ids["seller_a"]
    )
