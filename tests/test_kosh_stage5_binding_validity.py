"""Regression tests for binding-plan validity, allocation alignment and proof enforcement.

Asserts:
1. When guaranteed financing is INSUFFICIENT and collections are VALID:
   - overall status remains INSUFFICIENT;
   - real persisted line exists with status == 'INSUFFICIENT';
   - create_from_plan_line raises ValueError('VALID_PLAN_REQUIRED').
2. When binding plan is VALID, stored proof, costs and lines match binding allocation
   even when expected collections allocation differs.
3. In target_scope == 'ALL_WEEKS', action creation proof verifies every week <= target.
4. NBFC baseline comparison excludes collections.
"""
from decimal import Decimal
from datetime import date, timedelta
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.finance.plan import propose_plan
from app.actions.planner import create_from_plan_line
from app.database.models import SellerRevision, SellerAttribute
from app.database.kosh_models import (
    KoshPlan,
    KoshPlanLine,
    KoshInvoice,
    KoshCounterparty,
)
from tests.matching_factories import make_seller
from tests.conftest import sign_in


@pytest.fixture(autouse=True)
def configure_kosh_env(monkeypatch):
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_binding_status_insufficient_when_guaranteed_fails_but_collections_pass(client, db, monkeypatch):
    """Collections-only VALID must not make the binding status VALID.

    Scenario: A seller with a cash shortfall has small TReDS capacity that cannot
    close the gap, but large Collections capacity that can.
    - Guaranteed plan: INSUFFICIENT
    - Expected plan: VALID
    - Overall plan: INSUFFICIENT
    - Persisted lines: 1 real line with status == 'INSUFFICIENT'
    - Action gate: raises ValueError('VALID_PLAN_REQUIRED')
    """
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-binding-test1"
    seller = make_seller(db, name="BindingGuard Seller", owner_subject=subject)

    party_treds = KoshCounterparty(
        seller_id=seller.id, name="Buyer BG TReDS", kind="CUSTOMER", treds_onboarded=True,
    )
    party_regular = KoshCounterparty(
        seller_id=seller.id, name="Buyer BG Regular", kind="CUSTOMER", treds_onboarded=False,
    )
    db.add_all([party_treds, party_regular])
    db.flush()

    rev = db.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).one()
    db.add(SellerAttribute(revision_id=rev.id, key="cash_buffer_paise", value_type="NUMBER", value_number=10_000_000))
    db.commit()

    # TReDS invoice (guaranteed capacity: 2,000,000 paise).
    # 2M < 10M buffer, so guaranteed plan alone CANNOT close the shortfall.
    inv_treds = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_treds.id, direction="RECEIVABLE",
        invoice_number="INV-BG-TREDS", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 11, 20), amount_paise=2_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_treds)

    # Collection invoice on non-TReDS buyer (due in 7 days, <=30 days).
    # 30M invoice gives 15M collections capacity > 10M buffer, closing the shortfall.
    inv_col = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_regular.id, direction="RECEIVABLE",
        invoice_number="INV-BG-COL-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 20), amount_paise=30_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_col)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALERT_WEEK", persist=True)
    db.commit()

    g_status = plan.planning_details["guaranteed_status"]
    e_status = plan.planning_details["expected_plan"]["status"]
    overall = plan.status

    # Unconditional status checks: guaranteed fails, collections pass, overall stays INSUFFICIENT
    assert g_status == "INSUFFICIENT"
    assert e_status == "VALID"
    assert overall == "INSUFFICIENT"

    # Persisted lines check: real line exists representing the binding allocation
    lines = db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id)).all()
    assert len(lines) == 1
    line = lines[0]
    assert line.product_id == "TREDS_INVOICE_DISCOUNTING"
    assert line.amount_paise == 2_000_000
    assert line.status == "INSUFFICIENT"

    # Action creation gate check: must reject non-VALID plan
    with pytest.raises(ValueError, match="VALID_PLAN_REQUIRED"):
        create_from_plan_line(db, seller_id=seller.id, plan_line_id=line.id, creator_id=1)


def test_binding_plan_amounts_and_costs_match_guaranteed_allocation(client, db, monkeypatch):
    """When a plan is VALID, stored proof, costs and lines match the guaranteed allocation.

    Even when the expected plan includes zero-cost collections levers, the executable
    financing allocation, total cost, after_probabilities and persisted KoshPlanLine rows
    must consistently represent the financing-only binding plan.
    """
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-binding-test2"
    seller = make_seller(db, name="BindingValid Seller", owner_subject=subject)

    party_treds = KoshCounterparty(
        seller_id=seller.id, name="Buyer BV TReDS", kind="CUSTOMER", treds_onboarded=True,
    )
    party_regular = KoshCounterparty(
        seller_id=seller.id, name="Buyer BV Regular", kind="CUSTOMER", treds_onboarded=False,
    )
    db.add_all([party_treds, party_regular])
    db.flush()

    rev = db.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).one()
    db.add(SellerAttribute(revision_id=rev.id, key="cash_buffer_paise", value_type="NUMBER", value_number=10_000_000))
    db.commit()

    # Large TReDS invoice (guaranteed capacity: 15,000,000 paise > 10,000,000 buffer)
    inv_treds = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_treds.id, direction="RECEIVABLE",
        invoice_number="INV-BV-TREDS", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 11, 20), amount_paise=15_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_treds)

    # Collection invoice on non-TReDS buyer
    inv_col = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_regular.id, direction="RECEIVABLE",
        invoice_number="INV-BV-COL-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 20), amount_paise=20_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_col)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALERT_WEEK", persist=True)
    db.commit()

    g_status = plan.planning_details["guaranteed_status"]
    e_status = plan.planning_details["expected_plan"]["status"]
    assert g_status == "VALID"
    assert e_status == "VALID"
    assert plan.status == "VALID"

    # Cost and probabilities must match guaranteed allocation, NOT expected plan
    assert plan.total_cost_paise == plan.planning_details["guaranteed_total_cost_paise"]
    assert plan.total_cost_paise > 0
    assert plan.after_probabilities == plan.planning_details["guaranteed_plan"]["after_probabilities"]

    # Explicitly assert that expected and binding allocations differ
    expected_lines = plan.planning_details["expected_plan"]["lines"]
    guaranteed_lines = plan.planning_details["guaranteed_plan"]["lines"]
    assert expected_lines != guaranteed_lines, "Expected and binding allocations must differ"
    assert any(l["product_id"] == "COLLECTIONS_PUSH" for l in expected_lines), "Expected plan should include collections"
    assert all(l["product_id"] != "COLLECTIONS_PUSH" for l in guaranteed_lines), "Guaranteed plan must exclude collections"

    # Persisted lines must be financing-only and match guaranteed_plan.lines
    lines = db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id)).all()
    assert len(lines) == len(guaranteed_lines)
    for persisted_line, g_line in zip(lines, guaranteed_lines):
        assert persisted_line.product_id == g_line["product_id"]
        assert persisted_line.amount_paise == g_line["amount_paise"]
        assert persisted_line.cost_paise == g_line["cost_paise"]
        assert persisted_line.status == "VALID"
        assert persisted_line.product_id != "COLLECTIONS_PUSH"


def test_all_weeks_action_proof_checks_every_week(client, db, monkeypatch):
    """In ALL_WEEKS scope, create_from_plan_line must verify all weeks <= target_probability."""
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-binding-test3"
    seller = make_seller(db, name="ProofCheck Seller", owner_subject=subject)

    party = KoshCounterparty(
        seller_id=seller.id, name="Buyer PC", kind="CUSTOMER", treds_onboarded=True,
    )
    db.add(party)
    db.flush()

    rev = db.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).one()
    db.add(SellerAttribute(revision_id=rev.id, key="cash_buffer_paise", value_type="NUMBER", value_number=10_000_000))
    db.commit()

    inv = KoshInvoice(
        seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
        invoice_number="INV-PC-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 11, 20), amount_paise=15_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALL_WEEKS", persist=True)
    db.commit()

    lines = db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id)).all()
    assert len(lines) >= 1
    line = lines[0]

    # Test Case 1: When a non-alert week exceeds the target_probability in ALL_WEEKS mode,
    # action creation must raise PLAN_PROOF_INVALID even if the alert week is below target.
    original_probs = list(plan.after_probabilities)
    tampered_probs = list(original_probs)
    tampered_probs[4] = 0.25  # Week 5 exceeds 0.20 target, but is below 0.50 threshold
    plan.after_probabilities = tampered_probs
    db.commit()

    with pytest.raises(ValueError, match="PLAN_PROOF_INVALID"):
        create_from_plan_line(db, seller_id=seller.id, plan_line_id=line.id, creator_id=1)

    # Test Case 2: When all weeks are <= target_probability, verification passes
    valid_probs = [0.10] * len(original_probs)
    plan.after_probabilities = valid_probs
    db.commit()

    # Must not raise PLAN_PROOF_INVALID (may succeed or raise later date/module check, but not proof)
    try:
        create_from_plan_line(db, seller_id=seller.id, plan_line_id=line.id, creator_id=1)
        passed_proof = True
    except ValueError as e:
        passed_proof = (str(e) != "PLAN_PROOF_INVALID")
    assert passed_proof, "Proof verification should pass when all weeks <= target_probability"


def test_nbfc_baseline_excludes_collections(client, db, monkeypatch):
    """The NBFC comparison baseline must not include COLLECTIONS_PUSH levers.

    A real, non-empty NBFC allocation must be generated and meet the same
    target and scope without collections.
    """
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-baseline-test"
    seller = make_seller(db, name="BaselineCheck Seller", owner_subject=subject)

    # Set up cash shortfall and criteria to make NBFC_UNSECURED_BUSINESS_LOAN MATCHED
    rev = db.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).one()
    db.add(SellerAttribute(revision_id=rev.id, key="cash_buffer_paise", value_type="NUMBER", value_number=10_000_000))
    db.add(SellerAttribute(revision_id=rev.id, key="gstin", value_type="TEXT", value_text="29ABCDE1234F1Z5"))
    db.add(SellerAttribute(revision_id=rev.id, key="incorporation_date", value_type="TEXT", value_text="2020-01-01"))
    db.commit()

    party_treds = KoshCounterparty(
        seller_id=seller.id, name="Buyer BL TReDS", kind="CUSTOMER", treds_onboarded=True,
    )
    party_reg = KoshCounterparty(
        seller_id=seller.id, name="Buyer BL Regular", kind="CUSTOMER", treds_onboarded=False,
    )
    db.add_all([party_treds, party_reg])
    db.flush()

    inv_treds = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_treds.id, direction="RECEIVABLE",
        invoice_number="INV-BL-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 11, 20), amount_paise=5_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    # Non-TReDS invoice eligible for COLLECTIONS_PUSH (operational lever)
    inv_col = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_reg.id, direction="RECEIVABLE",
        invoice_number="INV-BL-COL", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 20), amount_paise=20_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add_all([inv_treds, inv_col])
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan_data = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALERT_WEEK", persist=False)

    baseline_lines = plan_data.get("planning_details", {}).get("baseline_lines", [])
    assert len(baseline_lines) > 0, "NBFC baseline must have a real, non-empty allocation"
    assert all(line["product_id"] == "NBFC_UNSECURED_BUSINESS_LOAN" for line in baseline_lines)
    assert all(line["amount_paise"] > 0 for line in baseline_lines)
    assert plan_data["planning_details"]["baseline_status"] == "VALID"

    baseline_product_ids = {line["product_id"] for line in baseline_lines}
    assert "COLLECTIONS_PUSH" not in baseline_product_ids, (
        "NBFC baseline must not include COLLECTIONS_PUSH; got: " + str(baseline_product_ids)
    )

    # Assert baseline meets the same target and scope without collections
    target_idx = plan_data["planning_details"]["alert_week"] - 1
    baseline_prob = plan_data["planning_details"]["baseline_after_probabilities"][target_idx]
    assert baseline_prob <= Decimal(".20"), f"Baseline probability {baseline_prob} must meet target 0.20"


def test_separate_collections_workflow_requires_approval_and_preserves_cash(client, db, monkeypatch):
    """Demonstrate existing separate collections workflow.

    - Create a reminder through the normal collections path (draft -> intent).
    - Prove execution before T2 approval is rejected and creates no outbox entry.
    - Approve and execute through the existing gate.
    - Assert exactly one simulated reminder is created.
    - Assert cash and forecast probabilities remain unchanged.
    - Keep collections excluded from binding financing lines.
    - No alternative approval bypass exists.
    """
    from sqlalchemy import func
    from app.actions.approvals import approve, ActionError
    from app.actions.execution import execute
    from app.policy.controls import editable_control
    from app.utils.dates import utcnow
    from app.database.kosh_models import (
        KoshSandboxOutbox,
        KoshSandboxLedgerEntry,
        KoshForecastRun,
        KoshForecastWeek,
        KoshActionIntent,
    )

    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-coll-workflow"
    seller = make_seller(db, name="CollectionsWorkflow Seller", owner_subject=subject)

    party = KoshCounterparty(
        seller_id=seller.id, name="Buyer CW", kind="CUSTOMER", treds_onboarded=False,
    )
    db.add(party)
    db.flush()

    # Pre-configure allowlist with satisfied 24-hour cool-off
    ctrl = editable_control(db, seller.id)
    ctrl.allowlist = [{"key": f"counterparty:{party.id}", "added_at": (utcnow() - timedelta(days=2)).isoformat() + "Z"}]
    db.commit()

    inv = KoshInvoice(
        seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
        invoice_number="INV-CW-01", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 20), amount_paise=10_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    from app.database.auth_models import AppUser
    user_id = db.scalar(select(AppUser.id).where(AppUser.supabase_user_id == subject))
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    db.commit()

    # Capture pre-execution forecast state
    pre_run = db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id == seller.id).order_by(KoshForecastRun.id.desc()).limit(1))
    pre_weeks = db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id == pre_run.id).order_by(KoshForecastWeek.week_index)).all()
    pre_probs = [w.prob_below_buffer for w in pre_weeks]
    pre_balances = [w.p50_closing_balance_paise for w in pre_weeks]

    # 1. Create a reminder through the normal collections path: POST /drafts then POST /drafts/{id}/intent
    draft_res = client.post(f"{prefix}/collections/drafts", json={"invoice_id": inv.id, "channel": "EMAIL", "tone": "PROFESSIONAL"})
    assert draft_res.status_code == 200
    draft_data = draft_res.json()
    assert draft_data["tier"] == "T1"
    draft_id = draft_data["id"]

    intent_res = client.post(f"{prefix}/collections/drafts/{draft_id}/intent")
    assert intent_res.status_code == 200
    intent_data = intent_res.json()
    intent_id = intent_data["id"]
    assert intent_data["tier"] == "T2"
    assert intent_data["action_type"] == "COLLECTIONS_REMINDER"
    assert intent_data["status"] == "PROPOSED"

    # Confirm collections intent is completely excluded from binding financing lines
    db.commit()
    intent_row = db.get(KoshActionIntent, intent_id)
    assert intent_row is not None
    assert intent_row.plan_line_id is None

    # 2. Prove execution before T2 approval is rejected and creates no outbox entry
    initial_outbox = db.scalars(select(func.count()).select_from(KoshSandboxOutbox)).one()
    initial_ledger = db.scalars(select(func.count()).select_from(KoshSandboxLedgerEntry)).one()
    assert initial_outbox == 0

    with pytest.raises(ActionError):
        execute(db, seller_id=seller.id, intent_id=intent_id, actor_id=user_id, token="unapproved.token.value")
    db.rollback()

    assert db.scalars(select(func.count()).select_from(KoshSandboxOutbox)).one() == 0

    # 3. Approve and execute through the existing gate
    approval_artifact, token = approve(db, seller_id=seller.id, intent_id=intent_id, actor_id=user_id)
    db.commit()

    exec_result = execute(db, seller_id=seller.id, intent_id=intent_id, actor_id=user_id, token=token)
    db.commit()

    # 4. Assert exactly one simulated reminder is created
    outbox_entries = db.scalars(select(KoshSandboxOutbox).where(KoshSandboxOutbox.intent_id == intent_id)).all()
    assert len(outbox_entries) == 1
    assert outbox_entries[0].status == "SUBMITTED"
    assert outbox_entries[0].channel == "EMAIL"
    assert outbox_entries[0].recipient_ref == f"counterparty:{party.id}"

    # 5. Assert cash and forecast probabilities remain unchanged
    # Zero ledger entries created (messaging does not change bank balance)
    ledger_entries = db.scalars(select(func.count()).select_from(KoshSandboxLedgerEntry)).one()
    assert ledger_entries == initial_ledger

    # Reforecast ran, but probabilities and balances are strictly identical
    post_run = db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id == seller.id).order_by(KoshForecastRun.id.desc()).limit(1))
    post_weeks = db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id == post_run.id).order_by(KoshForecastWeek.week_index)).all()
    post_probs = [w.prob_below_buffer for w in post_weeks]
    post_balances = [w.p50_closing_balance_paise for w in post_weeks]

    assert post_probs == pre_probs
    assert post_balances == pre_balances
    assert exec_result.result["before_probabilities"] == exec_result.result["after_probabilities"]

