"""Tests for Stage 5.4 demo snapshot payables and dev login demo seller access."""
from __future__ import annotations
import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.database.models import Seller
from app.database.auth_models import AppUser, SellerMembership
from app.database.kosh_models import KoshInvoice, KoshCounterparty
from app.finance.forecast import load_inputs


def test_dev_login_refused_in_production(settings, session_factory, source):
    """DEV_LOGIN_ENABLED must be strictly rejected when APP_ENV=production."""
    with pytest.raises(ValueError, match="DEV_LOGIN_ENABLED"):
        create_app(
            settings.model_copy(update={"dev_login_enabled": True, "app_env": "production", "auto_migrate": False}),
            session_factory=session_factory,
            collector_factory=source,
        )


def test_dev_login_grants_access_to_meenakshi_demo_seller(settings, session_factory, source):
    """Dev sign-in with ANY email automatically grants OWNER access to Meenakshi Precision Components."""
    with session_factory() as session:
        seller = Seller(name="Meenakshi Precision Components")
        session.add(seller)
        session.commit()
        seller_id = seller.id

    app = create_app(
        settings.model_copy(update={"dev_login_enabled": True}),
        session_factory=session_factory,
        collector_factory=source,
    )
    with TestClient(app) as client:
        r = client.post("/api/dev/login", json={"email": "judge_reviewer@kosh.local"})
        assert r.status_code == 200
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Check /api/sellers includes Meenakshi Precision Components
        res = client.get("/api/sellers", headers=headers)
        assert res.status_code == 200
        sellers = res.json()
        matching = [s for s in sellers if s["id"] == seller_id]
        assert len(matching) == 1
        assert matching[0]["name"] == "Meenakshi Precision Components"

        # Check access to Kosh ledger API as OWNER
        ledger_res = client.get(f"/api/kosh/sellers/{seller_id}/ledger", headers=headers)
        assert ledger_res.status_code == 200
        assert ledger_res.json()["seller_id"] == seller_id


def test_ledger_excludes_review_payables_and_matches_forecast(session_factory):
    """Open payables in snapshot must exclude invoices held for review, matching load_inputs."""
    as_of = date(2026, 10, 13)
    with session_factory() as session:
        seller = Seller(name="Test Meenakshi")
        session.add(seller)
        session.flush()

        party = KoshCounterparty(seller_id=seller.id, name="Supplier A", kind="SUPPLIER")
        session.add(party)
        session.flush()

        # 1 verified payable
        inv1 = KoshInvoice(
            seller_id=seller.id,
            counterparty_id=party.id,
            direction="PAYABLE",
            invoice_number="MPC-P-001",
            invoice_date=date(2026, 10, 1),
            due_date=date(2026, 10, 30),
            amount_paise=10_000_000,
            status="OPEN",
        )
        # 1 held for review payable (e.g. poisoned invoice)
        inv_review = KoshInvoice(
            seller_id=seller.id,
            counterparty_id=party.id,
            direction="PAYABLE",
            invoice_number="POISON-001",
            invoice_date=date(2026, 10, 10),
            due_date=date(2026, 11, 9),
            amount_paise=48_000_000,
            status="REVIEW",
        )
        session.add_all([inv1, inv_review])
        session.commit()

        from app.api.cash import get_ledger
        ledger = get_ledger(seller.id, session, None)
        totals = ledger["totals"]

        # Verified open payables must be 10,000,000 (excluding the 48,000,000 in review)
        assert totals["open_payables_paise"] == 10_000_000
        assert totals["held_for_review_payables_paise"] == 48_000_000
        assert totals["held_for_review_paise"] == 48_000_000
        assert totals["review_count"] == 1

        # Forecast load_inputs must have exactly the same committed open payables
        inputs = load_inputs(session, seller.id, as_of)
        open_payables_forecast = sum(inv["amount_paise"] for inv in inputs.invoices if inv["direction"] == "PAYABLE")
        assert open_payables_forecast == totals["open_payables_paise"]
        assert inputs.under_review_paise == totals["held_for_review_paise"]
