"""Tests for financing eligibility evidence capture, re-evaluation, and plan freshness."""
from datetime import date, timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select, func

from app.database.auth_models import SellerMembership
from app.database.kosh_models import (
    KoshInvoice,
    KoshCounterparty,
    KoshForecastRun,
    KoshForecastWeek,
    KoshAuditEntry,
    KoshCashEvent,
    KoshSandboxOutbox,
    KoshActionIntent,
    KoshPlan,
    KoshPlanLine,
    KoshFinancingEvaluation,
    KoshFinancingResult,
)
from app.database.models import SellerRevision, SellerAttribute
from app.actions.planner import create_from_plan_line
from app.audit.verify import verify_chain
from tests.test_kosh_stage4_intents import planned_line, SUBJECT
from tests.conftest import sign_in


def _setup_seller_with_forecast_and_plan(db, *, name="Financing Seller", subject=SUBJECT):
    seller, user, invoice, line = planned_line(db, name=name, subject=subject)
    # Ensure active SellerRevision has baseline business profile (like seed-42)
    rev = db.scalar(select(SellerRevision).where(SellerRevision.seller_id == seller.id, SellerRevision.is_active.is_(True)).order_by(SellerRevision.revision_number.desc()).limit(1))
    db.add(SellerAttribute(revision_id=rev.id, key="udyam_number", value_type="TEXT", value_text="UDYAM-KA-03-0012345", context="Self-declared; certificate deliberately absent"))
    db.add(SellerAttribute(revision_id=rev.id, key="udyam_category", value_type="TEXT", value_text="SMALL", context="Self-declared"))
    db.add(SellerAttribute(revision_id=rev.id, key="gstin", value_type="TEXT", value_text="29ABCDE1234F1Z5", context="Self-declared business profile"))
    db.add(SellerAttribute(revision_id=rev.id, key="last_fy_turnover_paise", value_type="NUMBER", value_number=6487351240.0, context="FY 2025-26 self-declared"))
    db.add(SellerAttribute(revision_id=rev.id, key="bank_od_limit_paise", value_type="NUMBER", value_number=300000000.0, context="Bank statement attribute"))
    db.add(SellerAttribute(revision_id=rev.id, key="bank_od_utilised_paise", value_type="NUMBER", value_number=120000000.0, context="Bank statement attribute"))
    db.flush()

    # Ensure forecast run has forecast weeks for peak shortfall calculation
    run = db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id == seller.id).order_by(KoshForecastRun.id.desc()).limit(1))
    week = db.scalar(select(KoshForecastWeek).where(KoshForecastWeek.run_id == run.id))
    if not week:
        db.add(KoshForecastWeek(
            run_id=run.id,
            week_index=1,
            week_start=date(2026, 10, 13),
            week_end=date(2026, 10, 19),
            p10_closing_balance_paise=1000000,
            p50_closing_balance_paise=2000000,
            p90_closing_balance_paise=3000000,
            expected_inflow_committed_paise=500000,
            expected_inflow_forecast_paise=0,
            expected_outflow_committed_paise=300000,
            expected_outflow_forecast_paise=0,
            prob_below_buffer=0.10,
            expected_shortfall_paise=40000000,  # 4 lakh (Kishore Mudra band)
        ))
        db.flush()

    # Also add a payable invoice to verify payable dates are never altered
    supplier = KoshCounterparty(seller_id=seller.id, name="Raw Steel Supplier", kind="SUPPLIER", treds_onboarded=False)
    db.add(supplier)
    db.flush()
    payable = KoshInvoice(
        seller_id=seller.id,
        counterparty_id=supplier.id,
        direction="PAYABLE",
        invoice_number=f"BILL-{seller.id}-001",
        invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 25),
        amount_paise=5000000,
        status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(payable)
    db.commit()
    return seller, user, invoice, payable, line


def test_owner_access_and_rejection_boundaries(client, db, monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv('SUPABASE_URL', 'https://kosh-tests.supabase.co')
    get_token_verifier.cache_clear()
    seller, user, invoice, payable, _ = _setup_seller_with_forecast_and_plan(db)
    other, _, _, _, _ = _setup_seller_with_forecast_and_plan(db, name="Other Seller", subject="22222222-3333-4444-5555-666666666666")
    prefix = f"/api/kosh/sellers/{seller.id}/financing/evidence"

    # 1. Unauthenticated gets 401
    resp = client.get(prefix)
    assert resp.status_code == 401
    resp = client.put(prefix, json={"non_corporate": True})
    assert resp.status_code == 401

    sign_in(client.app, SUBJECT)

    # 2. Owner can read evidence (200)
    resp = client.get(prefix)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["role"] == "OWNER"
    assert data["seller_id"] == seller.id
    assert "evidence" in data
    assert "missing_criteria" in data
    assert "fixtures" in data
    assert len(data["fixtures"]) >= 4

    # 3. Owner can write evidence (200)
    resp = client.put(prefix, json={
        "non_corporate": True,
        "non_farm": True,
        "income_generating": True,
        "micro_small_enterprise": True,
        "evidence_ref": "Owner declaration at intake",
    })
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["status"] == "RECORDED"
    assert "options" in result

    # 4. Non-owner roles (VIEWER, APPROVER, EDITOR) rejected with 403
    member = db.scalar(select(SellerMembership).where(SellerMembership.user_id == user.id, SellerMembership.seller_id == seller.id))
    for forbidden_role in ("VIEWER", "APPROVER", "EDITOR"):
        member.role = forbidden_role
        db.commit()
        resp = client.put(prefix, json={"non_corporate": True})
        assert resp.status_code == 403, (forbidden_role, resp.status_code)

    # Restore OWNER
    member.role = "OWNER"
    db.commit()

    # 5. Cross-tenant access rejected with 403
    other_prefix = f"/api/kosh/sellers/{other.id}/financing/evidence"
    resp = client.get(other_prefix)
    assert resp.status_code == 403
    resp = client.put(other_prefix, json={"non_corporate": True})
    assert resp.status_code == 403


def test_all_three_eligibility_outcomes_and_criterion_reasons(client, db):
    seller, user, _, _, _ = _setup_seller_with_forecast_and_plan(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/financing/evidence"

    # Outcome 1: REVIEW_REQUIRED (Initial state: unrecorded facts)
    resp = client.get(prefix)
    assert resp.status_code == 200
    missing = resp.json()["missing_criteria"]
    mudra_missing = next(p for p in missing if p["product_id"] == "MUDRA_LOAN")
    assert any(c["criterion"] == "NON_CORPORATE" and c["status"] == "MISSING" for c in mudra_missing["criteria"])

    # Outcome 2: MATCHED (Complete evidence satisfying scheme criteria)
    resp = client.put(prefix, json={
        "non_corporate": True,
        "non_farm": True,
        "income_generating": True,
        "micro_small_enterprise": True,
        "tarun_availed_and_repaid": True,
        "udyam_certificate_present": True,
        "supplier_relationship_months": 24,
        "supplier_on_time_ratio": 0.95,
        "supplier_extension_status": "CONFIRMED",
        "evidence_ref": "Audit ref: verified-documents-2026",
    })
    assert resp.status_code == 200
    options = resp.json()["options"]
    mudra = next(p for p in options if p["product_id"] == "MUDRA_LOAN")
    cgtmse = next(p for p in options if p["product_id"] == "CGTMSE_BACKED_WC_LOAN")
    supplier_ext = next(p for p in options if p["product_id"] == "SUPPLIER_TERM_EXTENSION")
    gem_sahay = next(p for p in options if p["product_id"] == "GEM_SAHAY_PO_FINANCE")

    assert mudra["status"] == "MATCHED"
    assert all(r["status"] != "NOT_MATCHED" for r in mudra["reasons"])
    # Criterion level reasons
    non_corp_reason = next(r for r in mudra["reasons"] if r["criterion"] == "NON_CORPORATE")
    assert non_corp_reason["status"] == "MATCHED"
    assert non_corp_reason["reason_code"] == "CRITERION_MET"
    assert non_corp_reason["business_evidence"]["value"] is True
    assert non_corp_reason["business_evidence"]["source"]["origin"] == "OWNER_RECORDED"

    assert cgtmse["status"] == "MATCHED"
    assert supplier_ext["status"] == "MATCHED"
    # GeM Sahay remains REVIEW_REQUIRED because product is under revision in catalogue
    assert gem_sahay["status"] == "REVIEW_REQUIRED"

    # Outcome 3: NOT_MATCHED (Confirmed evidence failing scheme rules)
    resp = client.put(prefix, json={
        "non_corporate": True,
        "non_farm": False,  # Fails non-farm requirement
        "income_generating": True,
        "micro_small_enterprise": True,
        "supplier_relationship_months": 6,  # Fails min 12 months requirement
        "supplier_on_time_ratio": 0.65,     # Fails min 80% on-time ratio
        "evidence_ref": "Farm enterprise declaration",
    })
    assert resp.status_code == 200
    options = resp.json()["options"]
    mudra_failed = next(p for p in options if p["product_id"] == "MUDRA_LOAN")
    supplier_failed = next(p for p in options if p["product_id"] == "SUPPLIER_TERM_EXTENSION")

    assert mudra_failed["status"] == "NOT_MATCHED"
    non_farm_reason = next(r for r in mudra_failed["reasons"] if r["criterion"] == "NON_FARM")
    assert non_farm_reason["status"] == "NOT_MATCHED"
    assert non_farm_reason["reason_code"] == "CRITERION_FAILED"
    assert "does not meet this criterion" in non_farm_reason["reason"]

    assert supplier_failed["status"] == "NOT_MATCHED"
    rel_reason = next(r for r in supplier_failed["reasons"] if r["criterion"] == "SUPPLIER_RELATIONSHIP_MIN_MONTHS")
    assert rel_reason["status"] == "NOT_MATCHED"
    assert rel_reason["reason_code"] == "CRITERION_FAILED"


def test_evidence_revisions_audit_recording_and_plan_freshness(client, db):
    seller, user, invoice, _, line = _setup_seller_with_forecast_and_plan(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/financing/evidence"

    plan = db.get(KoshPlan, line.plan_id)
    assert plan.status == "VALID"

    audit_before = db.scalar(select(func.count()).select_from(KoshAuditEntry).where(KoshAuditEntry.seller_id == seller.id))

    # Save evidence revision
    resp = client.put(prefix, json={
        "non_corporate": True,
        "non_farm": True,
        "evidence_ref": "audit-proof-revision-1",
    })
    assert resp.status_code == 200
    db.rollback()

    # 1. Audit recorded in existing append-only hash chain
    audit_after = db.scalar(select(func.count()).select_from(KoshAuditEntry).where(KoshAuditEntry.seller_id == seller.id))
    assert audit_after == audit_before + 1
    last_audit = db.scalar(select(KoshAuditEntry).where(KoshAuditEntry.seller_id == seller.id).order_by(KoshAuditEntry.sequence.desc()).limit(1))
    assert last_audit.action == "financing.evidence"
    assert last_audit.payload["evidence_ref"] == "audit-proof-revision-1"
    assert verify_chain(db).valid

    # 2. Affected plan is marked STALE
    db.refresh(plan)
    assert plan.status == "STALE"
    assert "evidence changed" in plan.planning_details.get("why_this_plan", "").lower()

    # 3. Action cannot be created from stale plan line without replanning
    with pytest.raises(ValueError, match="VALID_PLAN_REQUIRED"):
        create_from_plan_line(db, seller_id=seller.id, plan_line_id=line.id, creator_id=user.id)


def test_zero_outbound_side_effects(client, db):
    seller, user, invoice, payable, _ = _setup_seller_with_forecast_and_plan(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/financing/evidence"

    cash_events_before = db.scalar(select(func.count()).select_from(KoshCashEvent))
    outbox_before = db.scalar(select(func.count()).select_from(KoshSandboxOutbox))
    intents_before = db.scalar(select(func.count()).select_from(KoshActionIntent))
    payable_due_before = payable.due_date
    payable_amount_before = payable.amount_paise

    # Save evidence
    resp = client.put(prefix, json={
        "supplier_relationship_months": 24,
        "supplier_on_time_ratio": 0.95,
        "supplier_extension_status": "PROPOSED",
        "evidence_ref": "zero-side-effects-proof",
    })
    assert resp.status_code == 200

    # Ensure no cash events, no outbox messages, no action intents were created
    assert db.scalar(select(func.count()).select_from(KoshCashEvent)) == cash_events_before
    assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox)) == outbox_before
    assert db.scalar(select(func.count()).select_from(KoshActionIntent)) == intents_before

    # Ensure payable due date and amount are strictly unchanged
    db.refresh(payable)
    assert payable.due_date == payable_due_before
    assert payable.amount_paise == payable_amount_before


def test_supplier_extension_proposal_vs_confirmed_agreement(client, db):
    seller, user, invoice, payable, _ = _setup_seller_with_forecast_and_plan(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/financing/evidence"

    original_due_date = payable.due_date

    # 1. Proposal
    resp = client.put(prefix, json={
        "supplier_relationship_months": 18,
        "supplier_on_time_ratio": 0.90,
        "supplier_extension_status": "PROPOSED",
        "evidence_ref": "email-to-supplier:extension-proposal",
    })
    assert resp.status_code == 200
    evidence_resp = client.get(prefix).json()
    assert evidence_resp["evidence"]["supplier_extension_status"] == "PROPOSED"
    db.refresh(payable)
    assert payable.due_date == original_due_date

    # 2. Confirmed Agreement
    resp = client.put(prefix, json={
        "supplier_relationship_months": 18,
        "supplier_on_time_ratio": 0.90,
        "supplier_extension_status": "CONFIRMED",
        "evidence_ref": "signed-addendum-supplier-2026",
    })
    assert resp.status_code == 200
    evidence_resp = client.get(prefix).json()
    assert evidence_resp["evidence"]["supplier_extension_status"] == "CONFIRMED"
    db.refresh(payable)
    assert payable.due_date == original_due_date


def test_demonstration_fixtures(client, db):
    seller, user, _, _, _ = _setup_seller_with_forecast_and_plan(db)
    sign_in(client.app, SUBJECT)
    prefix = f"/api/kosh/sellers/{seller.id}/financing/evidence"

    # 1. Apply Legitimate Match Fixture
    resp = client.put(prefix, json={"apply_fixture": "FICT-MATCH-001"})
    assert resp.status_code == 200
    options = resp.json()["options"]
    assert next(p for p in options if p["product_id"] == "MUDRA_LOAN")["status"] == "MATCHED"
    assert next(p for p in options if p["product_id"] == "CGTMSE_BACKED_WC_LOAN")["status"] == "MATCHED"

    # 2. Apply Failing Fixture
    resp = client.put(prefix, json={"apply_fixture": "FICT-FAIL-002"})
    assert resp.status_code == 200
    options = resp.json()["options"]
    assert next(p for p in options if p["product_id"] == "MUDRA_LOAN")["status"] == "NOT_MATCHED"
    assert next(p for p in options if p["product_id"] == "SUPPLIER_TERM_EXTENSION")["status"] == "NOT_MATCHED"

    # 3. Apply Review Fixture
    resp = client.put(prefix, json={"apply_fixture": "FICT-REVIEW-003"})
    assert resp.status_code == 200
    options = resp.json()["options"]
    assert next(p for p in options if p["product_id"] == "MUDRA_LOAN")["status"] == "REVIEW_REQUIRED"

    # 4. Apply Proposed Supplier Extension Fixture
    resp = client.put(prefix, json={"apply_fixture": "FICT-SUPPLIER-PROPOSED"})
    assert resp.status_code == 200
    ev = client.get(prefix).json()["evidence"]
    assert ev["supplier_extension_status"] == "PROPOSED"
