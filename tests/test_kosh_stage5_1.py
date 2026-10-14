"""Stage 5.1 tests: owner invoice evidence, statutory interest, and plan freshness."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import pytest
from sqlalchemy import select, func

from app.finance.collections import msmed_interest
from app.database.auth_models import SellerMembership
from app.database.kosh_models import (
    KoshInvoice,
    KoshCollectionTerms,
    KoshAuditEntry,
    KoshCashEvent,
    KoshSandboxOutbox,
    KoshActionIntent,
    KoshPlan,
    KoshPlanLine,
)
from app.actions.planner import create_from_plan_line
from app.audit.verify import verify_chain
from tests.test_kosh_stage4_intents import planned_line, SUBJECT
from tests.conftest import sign_in


def test_owner_access_non_owner_rejection_and_wrong_seller(client, db):
    seller, user, invoice, _ = planned_line(db)
    other, _, _, _ = planned_line(db, name="Other Tenant Seller", subject="11111111-2222-3333-4444-555555555555")
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/collections"

    valid_payload = {
        "acceptance_date": "2026-10-01",
        "agreement_status": "NONE",
        "agreed_days": None,
        "supplier_mse": True,
        "evidence_ref": "PO-1234 Section 5",
    }

    # 1. Owner can record evidence
    resp = client.put(f"{prefix}/{invoice.id}/terms", json=valid_payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "DOCUMENTED"
    assert data["invoice_id"] == invoice.id
    assert data["principal_paise"] == invoice.amount_paise

    # 2. Non-owner roles rejected
    member = db.scalar(select(SellerMembership).where(SellerMembership.user_id == user.id, SellerMembership.seller_id == seller.id))
    for forbidden_role in ("VIEWER", "APPROVER", "EDITOR"):
        member.role = forbidden_role
        db.commit()
        resp = client.put(f"{prefix}/{invoice.id}/terms", json=valid_payload)
        assert resp.status_code == 403, (forbidden_role, resp.status_code)

    # Restore OWNER role
    member.role = "OWNER"
    db.commit()

    # 3. Wrong seller in path rejected with 403
    wrong_prefix = f"/api/kosh/sellers/{other.id}/collections"
    resp = client.put(f"{wrong_prefix}/{invoice.id}/terms", json=valid_payload)
    assert resp.status_code == 403

    # 4. Accessing other seller's invoice rejected with 404
    other_invoice = db.scalar(select(KoshInvoice).where(KoshInvoice.seller_id == other.id))
    assert other_invoice is not None
    resp = client.put(f"{prefix}/{other_invoice.id}/terms", json=valid_payload)
    assert resp.status_code == 404


def test_missing_and_invalid_evidence(client, db, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")
    get_settings.cache_clear()
    seller, user, invoice, _ = planned_line(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/collections"

    # Acceptance date boundary test relative to calculation as_of date (2026-10-13)
    # Exactly on as_of date: allowed
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-13",
        "agreement_status": "NONE",
        "supplier_mse": True,
        "evidence_ref": "boundary-on-as-of",
    })
    assert resp.status_code == 200, resp.text
    # Exactly one day after as_of date: rejected with clear validation message
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-14",
        "agreement_status": "NONE",
        "supplier_mse": True,
        "evidence_ref": "boundary-after-as-of",
    })
    assert resp.status_code == 422
    assert "future" in resp.text.lower()
    assert "2026-10-13" in resp.text

    # Acceptance date before invoice issue date
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": (invoice.invoice_date - timedelta(days=1)).isoformat(),
        "agreement_status": "NONE",
        "supplier_mse": True,
        "evidence_ref": "invalid-prior",
    })
    assert resp.status_code == 422
    assert "precede" in resp.text.lower()

    # AGREED with agreed_days > 45: explicitly rejected with clear validation message (not silently clamped)
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "AGREED",
        "agreed_days": 46,
        "supplier_mse": True,
        "evidence_ref": "over-45-days-credit",
    })
    assert resp.status_code == 422
    assert "cannot exceed 45 days" in resp.text or "less than or equal to 45" in resp.text

    # AGREED with agreed_days = 45: valid
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "AGREED",
        "agreed_days": 45,
        "supplier_mse": True,
        "evidence_ref": "valid-45-days-credit",
    })
    assert resp.status_code == 200

    # Switching from AGREED (with agreed_days) to NONE: old agreed_days cannot be retained
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "NONE",
        "agreed_days": None,
        "supplier_mse": True,
        "evidence_ref": "switched-to-none",
    })
    assert resp.status_code == 200
    db.rollback()
    terms_row = db.get(KoshCollectionTerms, invoice.id)
    assert terms_row.agreement_status == "NONE"
    assert terms_row.agreed_days is None

    # Switching to UNKNOWN: clears agreed_days and stays distinct
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": None,
        "agreement_status": "UNKNOWN",
        "agreed_days": None,
        "supplier_mse": None,
        "evidence_ref": "switched-to-unknown",
    })
    assert resp.status_code == 200
    db.rollback()
    terms_row = db.get(KoshCollectionTerms, invoice.id)
    assert terms_row.agreement_status == "UNKNOWN"
    assert terms_row.agreed_days is None
    assert terms_row.acceptance_date is None
    assert terms_row.supplier_mse is None

    # AGREED without agreed_days
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "AGREED",
        "agreed_days": None,
        "supplier_mse": True,
        "evidence_ref": "missing-days",
    })
    assert resp.status_code == 422

    # AGREED with negative days
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "AGREED",
        "agreed_days": -5,
        "supplier_mse": True,
        "evidence_ref": "negative-days",
    })
    assert resp.status_code == 422

    # NONE with agreed_days provided
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "NONE",
        "agreed_days": 15,
        "supplier_mse": True,
        "evidence_ref": "contradictory-days",
    })
    assert resp.status_code == 422

    # Unknown evidence: unknown stays unknown, results in REVIEW_REQUIRED with null interest
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": None,
        "agreement_status": "UNKNOWN",
        "agreed_days": None,
        "supplier_mse": None,
        "evidence_ref": "terms-not-found",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["interest"]["status"] == "REVIEW_REQUIRED"
    assert data["interest"]["interest_paise"] is None
    assert data["total_paise"] == invoice.amount_paise


def test_not_applicable_and_not_yet_overdue(client, db):
    seller, user, invoice, _ = planned_line(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/collections"

    # Not-applicable: supplier_mse is False
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "NONE",
        "agreed_days": None,
        "supplier_mse": False,
        "evidence_ref": "Large enterprise declaration",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["interest"]["status"] == "NOT_APPLICABLE"
    assert data["interest"]["interest_paise"] is None
    assert data["total_paise"] == invoice.amount_paise

    # Also string literal "NOT_APPLICABLE"
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "NONE",
        "agreed_days": None,
        "supplier_mse": "NOT_APPLICABLE",
        "evidence_ref": "Large enterprise declaration",
    })
    assert resp.status_code == 200
    assert resp.json()["interest"]["status"] == "NOT_APPLICABLE"

    # Not-yet-overdue: acceptance 2026-10-01, agreed 30 days => due 2026-10-31.
    # As of 2026-10-13, as_of < due_date. Overdue days must be 0, interest must be 0.
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "AGREED",
        "agreed_days": 30,
        "supplier_mse": True,
        "evidence_ref": "Contract clause 4: 30 days credit",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["interest"]["status"] == "COMPUTED"
    assert data["interest"]["overdue_days"] == 0
    assert data["interest"]["interest_paise"] == 0
    assert data["principal_paise"] == invoice.amount_paise
    assert data["total_paise"] == invoice.amount_paise


def test_payment_period_boundaries_and_monthly_rest_calculation():
    # Boundary: Section 15 payment periods
    accepted = date(2026, 1, 1)
    # NONE -> 15 days
    res = msmed_interest(100000, accepted, accepted + timedelta(days=15), agreement_status="NONE", supplier_mse=True, bank_rate="5.75")
    assert res["payment_period_days"] == 15 and res["interest_paise"] == 0
    # Day after due date -> overdue interest begins
    res_overdue = msmed_interest(100000, accepted, accepted + timedelta(days=16), agreement_status="NONE", supplier_mse=True, bank_rate="5.75")
    assert res_overdue["overdue_days"] == 1 and res_overdue["interest_paise"] > 0

    # AGREED 0 -> 0 days
    assert msmed_interest(100000, accepted, accepted, agreement_status="AGREED", agreed_days=0, supplier_mse=True)["payment_period_days"] == 0
    # AGREED 44 -> 44 days
    assert msmed_interest(100000, accepted, accepted + timedelta(days=44), agreement_status="AGREED", agreed_days=44, supplier_mse=True)["payment_period_days"] == 44
    # AGREED 45 -> 45 days
    assert msmed_interest(100000, accepted, accepted + timedelta(days=45), agreement_status="AGREED", agreed_days=45, supplier_mse=True)["payment_period_days"] == 45
    # AGREED 46 -> capped at 45 days (Section 15)
    assert msmed_interest(100000, accepted, accepted + timedelta(days=45), agreement_status="AGREED", agreed_days=46, supplier_mse=True)["payment_period_days"] == 45

    # Tested reference fixture: INR 100,000 accepted 2026-01-01, NONE agreed (due 2026-01-16), as-of 2026-03-16:
    # 2 monthly rests, 0 stub days, rate 17.25% p.a.
    fixture_calc = msmed_interest(10000000, date(2026, 1, 1), date(2026, 3, 16), agreement_status="NONE", supplier_mse=True, bank_rate="5.75")
    expected = int((Decimal(10000000) * ((1 + Decimal(".1725") / 12) ** 2 - 1)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    assert fixture_calc["monthly_rests"] == 2
    assert fixture_calc["stub_days"] == 0
    assert fixture_calc["interest_paise"] == expected == 289566  # INR 2,895.66


def test_evidence_edits_audit_recording_and_plan_freshness(client, db):
    seller, user, invoice, line = planned_line(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}"

    plan = db.get(KoshPlan, line.plan_id)
    assert plan.status == "VALID"
    assert line.status == "VALID"
    assert invoice.id in line.scope_ids

    # Count audit entries before
    audit_count_before = db.scalar(select(func.count()).select_from(KoshAuditEntry).where(KoshAuditEntry.seller_id == seller.id))

    # Edit terms for the scoped invoice
    resp = client.put(f"{prefix}/collections/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "NONE",
        "supplier_mse": True,
        "evidence_ref": "audit-and-freshness-proof",
    })
    assert resp.status_code == 200
    db.rollback()

    # 1. Audit recorded in existing append-only hash chain
    audit_count_after = db.scalar(select(func.count()).select_from(KoshAuditEntry).where(KoshAuditEntry.seller_id == seller.id))
    assert audit_count_after == audit_count_before + 1
    last_audit = db.scalar(select(KoshAuditEntry).where(KoshAuditEntry.seller_id == seller.id).order_by(KoshAuditEntry.sequence.desc()).limit(1))
    assert last_audit.action == "collections.terms"
    assert last_audit.payload["invoice_id"] == invoice.id
    assert last_audit.payload["evidence_ref"] == "audit-and-freshness-proof"
    chain_ver = verify_chain(db)
    assert chain_ver.valid

    # 2. Affected plan is invalidated (marked STALE)
    db.refresh(plan)
    assert plan.status == "STALE"
    assert "changed" in plan.planning_details.get("why_this_plan", "").lower()

    # 3. Cannot create intent from invalidated plan line
    with pytest.raises(ValueError, match="VALID_PLAN_REQUIRED"):
        create_from_plan_line(db, seller_id=seller.id, plan_line_id=line.id, creator_id=user.id)


def test_no_duplicate_cash_or_outbound_action(client, db):
    seller, user, invoice, _ = planned_line(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/collections"

    # Snapshot state counts before saving terms
    cash_events_before = db.scalar(select(func.count()).select_from(KoshCashEvent))
    outbox_before = db.scalar(select(func.count()).select_from(KoshSandboxOutbox))
    intents_before = db.scalar(select(func.count()).select_from(KoshActionIntent))
    invoice_amount_before = invoice.amount_paise

    # Save evidence
    resp = client.put(f"{prefix}/{invoice.id}/terms", json={
        "acceptance_date": "2026-10-01",
        "agreement_status": "NONE",
        "agreed_days": None,
        "supplier_mse": True,
        "evidence_ref": "no-cash-impact-evidence",
    })
    assert resp.status_code == 200

    # Ensure no cash events, no outbox messages, no intents were created
    assert db.scalar(select(func.count()).select_from(KoshCashEvent)) == cash_events_before
    assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox)) == outbox_before
    assert db.scalar(select(func.count()).select_from(KoshActionIntent)) == intents_before
    assert invoice.amount_paise == invoice_amount_before


def test_collections_listing_and_terms_endpoint(client, db):
    seller, user, invoice, _ = planned_line(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/collections"

    resp = client.get(prefix)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "open_invoices" in data
    assert "fixture" in data
    assert "as_of" in data
    assert data["fixture"]["invoice_number"] == "FICT-DEMO-001"
    assert data["fixture"]["interest"]["interest_paise"] == 289566

    # Test GET /{invoice_id}/terms
    resp_terms = client.get(f"{prefix}/{invoice.id}/terms")
    assert resp_terms.status_code == 200
    terms_data = resp_terms.json()
    assert terms_data["invoice_id"] == invoice.id
    assert terms_data["principal_paise"] == invoice.amount_paise
    assert "interest" in terms_data
    assert "total_paise" in terms_data
