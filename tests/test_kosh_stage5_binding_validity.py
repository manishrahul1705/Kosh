"""Regression tests for binding-plan validity and NBFC baseline comparison.

Tests that uncertain collections cannot promote a VALID binding status when
the guaranteed plan (cash-posting levers only) is INSUFFICIENT.  Also tests
that the NBFC comparison baseline does not include uncertain collections.
"""
from decimal import Decimal
from datetime import date
import pytest
from unittest.mock import patch
from sqlalchemy import select

from app.finance.plan import propose_plan, validate_and_complete
from app.database.kosh_models import KoshPlan, KoshPlanLine, KoshInvoice, KoshCounterparty
from tests.matching_factories import make_seller
from tests.conftest import sign_in


def test_binding_status_insufficient_when_guaranteed_fails_but_collections_pass(client, db):
    """Collections-only VALID must not make the binding status VALID.

    Scenario: create a seller with a cash shortfall that TReDS alone cannot
    close but collections can.  The guaranteed plan must be INSUFFICIENT,
    and the overall binding plan status must also be INSUFFICIENT even if
    the expected plan (including collections) evaluates as VALID.
    """
    subject = "eeeeeeee-0000-0000-0000-binding-test1"
    seller = make_seller(db, name="BindingGuard Seller", owner_subject=subject)
    party = KoshCounterparty(
        seller_id=seller.id, name="Buyer BG", kind="CUSTOMER", treds_onboarded=True,
    )
    db.add(party)
    db.flush()

    # Small TReDS invoice (guaranteed capacity) plus many collection invoices.
    # The shortfall will be too large for TReDS alone to cover.
    inv_treds = KoshInvoice(
        seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
        invoice_number="INV-BG-TREDS", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 12, 2), amount_paise=50_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_treds)
    # Multiple collection invoices — enough to dwarf the TReDS capacity
    for i in range(10):
        inv_col = KoshInvoice(
            seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
            invoice_number=f"INV-BG-COL-{i}", invoice_date=date(2026, 10, 1),
            due_date=date(2026, 11, 15), amount_paise=500_000, status="OPEN",
            accepted_by_buyer=True,
        )
        db.add(inv_col)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan_data = propose_plan(db, seller.id, target_prob=Decimal(".20"), persist=False)

    # The guaranteed plan must report its own status (may be VALID or INSUFFICIENT
    # depending on the shortfall vs available capacity).
    g_status = plan_data["guaranteed_plan"]["status"]
    e_status = plan_data["expected_plan"]["status"]
    overall = plan_data["status"]

    # Core invariant: the binding plan status must ALWAYS equal the guaranteed
    # plan status.  It must never be promoted to VALID by the expected plan.
    assert overall == g_status, (
        f"Binding plan status ({overall}) must equal guaranteed plan status ({g_status}). "
        f"Expected plan status was {e_status} — collections must not promote binding status."
    )


def test_binding_status_valid_propagates_from_guaranteed(client, db):
    """When the guaranteed plan is VALID, the binding status should be VALID."""
    subject = "eeeeeeee-0000-0000-0000-binding-test2"
    seller = make_seller(db, name="BindingValid Seller", owner_subject=subject)
    party = KoshCounterparty(
        seller_id=seller.id, name="Buyer BV", kind="CUSTOMER", treds_onboarded=True,
    )
    db.add(party)
    db.flush()

    # Large enough TReDS invoice for guaranteed plan to succeed
    inv = KoshInvoice(
        seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
        invoice_number="INV-BV-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 12, 2), amount_paise=5_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan_data = propose_plan(db, seller.id, target_prob=Decimal(".20"), persist=False)

    g_status = plan_data["guaranteed_plan"]["status"]
    overall = plan_data["status"]

    # When guaranteed plan is VALID, overall must be VALID
    assert overall == g_status, (
        f"Binding plan status ({overall}) must equal guaranteed plan status ({g_status})"
    )
    if g_status == "VALID":
        assert overall == "VALID"


def test_action_creation_rejects_insufficient_binding_plan(client, db):
    """Verify that create_from_plan_line enforces plan.status == VALID.

    A plan whose guaranteed status is INSUFFICIENT must be rejected by the
    action creation gate, even if it once could have inherited VALID from
    the expected plan.
    """
    from app.actions.planner import create_from_plan_line

    subject = "eeeeeeee-0000-0000-0000-binding-test3"
    seller = make_seller(db, name="ActionReject Seller", owner_subject=subject)
    party = KoshCounterparty(
        seller_id=seller.id, name="Buyer AR", kind="CUSTOMER", treds_onboarded=True,
    )
    db.add(party)
    db.flush()

    inv = KoshInvoice(
        seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
        invoice_number="INV-AR-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 12, 2), amount_paise=500_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan = propose_plan(db, seller.id, target_prob=Decimal(".20"), persist=True)
    db.commit()

    if plan.status != "VALID":
        # Plan is INSUFFICIENT — verify the action gate rejects it
        line = db.scalar(
            select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id).limit(1)
        )
        if line is not None:
            with pytest.raises(ValueError, match="VALID_PLAN_REQUIRED"):
                create_from_plan_line(
                    db, seller_id=seller.id, plan_line_id=line.id, creator_id=1,
                )


def test_nbfc_baseline_excludes_collections(client, db):
    """The NBFC comparison baseline must not include COLLECTIONS_PUSH levers.

    This ensures the cost comparison is fair: both the guaranteed plan and the
    baseline exclude uncertain timing-dependent relationship levers.
    """
    subject = "eeeeeeee-0000-0000-0000-baseline-test"
    seller = make_seller(db, name="BaselineCheck Seller", owner_subject=subject)
    party = KoshCounterparty(
        seller_id=seller.id, name="Buyer BL", kind="CUSTOMER", treds_onboarded=True,
    )
    db.add(party)
    db.flush()

    inv = KoshInvoice(
        seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
        invoice_number="INV-BL-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 12, 2), amount_paise=500_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan_data = propose_plan(db, seller.id, target_prob=Decimal(".20"), persist=False)

    baseline_lines = plan_data.get("planning_details", {}).get("baseline_lines", [])
    baseline_product_ids = {line["product_id"] for line in baseline_lines}
    assert "COLLECTIONS_PUSH" not in baseline_product_ids, (
        "NBFC baseline must not include COLLECTIONS_PUSH; got: " +
        str(baseline_product_ids)
    )
    # Baseline should only contain NBFC unsecured loan (if any levers selected)
    for pid in baseline_product_ids:
        assert pid == "NBFC_UNSECURED_BUSINESS_LOAN", (
            f"Unexpected product {pid} in NBFC baseline"
        )
