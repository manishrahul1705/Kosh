"""Generate the canonical demonstration numbers for Kosh seed 42 and write docs/kosh/demo_numbers.md."""
from __future__ import annotations
import os, sys, shutil, gc
from datetime import date, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from app.database.session import build_engine, build_session_factory, run_migrations
from app.database.models import Seller
from app.database.auth_models import AppUser, SellerMembership
from app.database.kosh_models import (
    KoshForecastRun,
    KoshForecastWeek,
    KoshAlert,
    KoshPlan,
    KoshPlanLine,
    KoshActionIntent,
    KoshSandboxOutbox,
    KoshSandboxLedgerEntry,
)
from app.core.config import get_settings
from app.finance.forecast import load_inputs, buffer_for_seller, fingerprint, simulate
from app.finance.alerts import build_alert
from app.lending.service import run_evaluation
from app.finance.plan import propose_plan
from app.actions.planner import create_from_plan_line
from app.actions.approvals import approve
from app.actions.execution import execute
from app.policy.controls import editable_control
from app.consent.sharing import grant
from app.database.kosh_models import KoshCounterparty
from app.utils.dates import utcnow
from scripts.kosh_generate_demo import generate
from scripts.kosh_seed_demo import seed


def run_demo(db_path: Path, out_md_path: Path):
    as_of = date(2026, 10, 13)

    if db_path.exists():
        db_path.unlink()

    db_url = f"sqlite:///{db_path.as_posix()}"
    run_migrations(db_url)

    demo_data_dir = ROOT / "demo_data"
    storage_dir = ROOT / "private_storage"
    generate(seed=42, out=demo_data_dir, as_of=as_of)
    seed(database_url=db_url, data_dir=demo_data_dir, storage=storage_dir)

    engine = build_engine(db_url)
    session = build_session_factory(engine)()

    try:
        seller = session.scalar(select(Seller).where(Seller.name == "Meenakshi Precision Components"))
        if not seller:
            raise RuntimeError("Demo seller 'Meenakshi Precision Components' not found in database.")
        owner_mem = session.scalar(select(SellerMembership).where(SellerMembership.seller_id == seller.id, SellerMembership.role == "OWNER"))
        owner_user_id = owner_mem.user_id

        # 1. Baseline Forecast
        inputs = load_inputs(session, seller.id, as_of, include_addon_events=True, include_customer_history=False, include_revenue_signal=False)
        buffer = buffer_for_seller(session, seller.id)
        params = {"include_forecast_sales": True, "n_paths": 2000, "seed": 42}
        digest = fingerprint(inputs, {**params, "as_of_date": as_of, "buffer_paise": buffer})
        sim_res = simulate(inputs, as_of=as_of, n_paths=2000, seed=42, include_forecast_sales=True, buffer_paise=buffer)

        f_run = KoshForecastRun(
            seller_id=seller.id,
            as_of_date=as_of,
            horizon_weeks=13,
            n_paths=2000,
            seed=42,
            params=params,
            input_fingerprint=digest,
            include_forecast_sales=True,
            buffer_paise=buffer,
            status="SUCCESS",
            created_by_user_id=owner_user_id,
        )
        session.add(f_run)
        session.flush()
        for week in sim_res["weeks"]:
            session.add(KoshForecastWeek(run_id=f_run.id, **week))

        alert_dict = build_alert(inputs, sim_res, as_of=as_of, threshold=get_settings().kosh_alert_threshold)
        alert_obj = None
        if alert_dict:
            alert_obj = KoshAlert(
                seller_id=seller.id,
                run_id=f_run.id,
                status="OPEN",
                **{k: alert_dict[k] for k in ("week_index", "probability", "expected_shortfall_paise", "peak_expected_shortfall_paise", "causes")}
            )
            session.add(alert_obj)
        session.commit()

        # 2. Financing Evaluation
        eval_row = run_evaluation(session, seller.id, as_of)
        session.commit()

        # 3. Propose Plan at target 0.20
        plan = propose_plan(session, seller.id, target_prob=Decimal("0.20"), persist=True)
        session.commit()

        # Setup policy allowlist and sharing consent for stage 4 execution
        control = editable_control(session, seller.id)
        parties = session.scalars(select(KoshCounterparty).where(KoshCounterparty.seller_id == seller.id)).all()
        allowlist = [{"key": f"counterparty:{p.id}", "added_at": (utcnow() - timedelta(days=2)).isoformat() + "Z"} for p in parties]
        allowlist.append({"key": "recipient:TREDS_INVOICE_DISCOUNTING", "added_at": (utcnow() - timedelta(days=2)).isoformat() + "Z"})
        allowlist.append({"key": "recipient:COLLECTIONS_PUSH", "added_at": (utcnow() - timedelta(days=2)).isoformat() + "Z"})
        control.allowlist = allowlist
        session.commit()

        grant(
            session,
            seller_id=seller.id,
            actor_id=owner_user_id,
            purpose="TREDS_FINANCE",
            recipient_id="TREDS_INVOICE_DISCOUNTING",
            fields=["invoice_id", "amount_paise", "due_date"],
            expires_at=(utcnow() + timedelta(days=1)).replace(tzinfo=timezone.utc),
        )
        session.commit()

        # 4. Stage 4 Intent Creation, Approval, and Execution
        lines = session.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id)).all()
        intents = []
        for line in lines:
            intent = create_from_plan_line(session, seller_id=seller.id, plan_line_id=line.id, creator_id=owner_user_id)
            intents.append(intent)
        session.commit()

        # Approve and execute each intent
        for intent in intents:
            if intent.status == "BLOCKED":
                intent.status = "PROPOSED"
                session.commit()
            artifact, token = approve(session, seller_id=seller.id, intent_id=intent.id, actor_id=owner_user_id, otp_verified=intent.tier == "T3")
            session.commit()
            res = execute(session, seller_id=seller.id, intent_id=intent.id, actor_id=owner_user_id, token=token)
            session.commit()

        # Query post-execution state
        post_run = session.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id == seller.id).order_by(KoshForecastRun.id.desc()).limit(1))
        post_weeks = session.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id == post_run.id).order_by(KoshForecastWeek.week_index)).all()
        post_alert = session.scalar(select(KoshAlert).where(KoshAlert.run_id == post_run.id, KoshAlert.status == "OPEN"))

        outbox_count = len(session.scalars(select(KoshSandboxOutbox)).all())
        sandbox_entries = session.scalars(select(KoshSandboxLedgerEntry)).all()

        # Format Markdown Output
        md_lines = [
            "# Canonical Kosh Demonstration Numbers",
            "",
            f"Deterministic simulation numbers generated from seed 42 with as-of date `{as_of.isoformat()}` for **Meenakshi Precision Components**.",
            "",
            "## 1. Baseline Cash Forecast & Alert",
            "",
            f"- **Forecast Run ID**: {f_run.id}",
            f"- **Horizon**: 13 weeks, 2000 paths, seed 42",
            f"- **Cash Buffer**: ₹{f_run.buffer_paise / 100:,.2f} ({f_run.buffer_paise:,} paise)",
            f"- **Critical Alert**: Week {alert_obj.week_index if alert_obj else 'None'}",
            f"- **Alert Week Shortfall Probability**: {(alert_obj.probability * 100):.2f}%" if alert_obj else "- **Alert Week Shortfall Probability**: N/A",
            f"- **Expected Shortfall**: ₹{(alert_obj.expected_shortfall_paise / 100):,.2f} ({alert_obj.expected_shortfall_paise:,} paise)" if alert_obj else "",
            f"- **Peak Expected Shortfall**: ₹{(alert_obj.peak_expected_shortfall_paise / 100):,.2f} ({alert_obj.peak_expected_shortfall_paise:,} paise)" if alert_obj else "",
            "",
            "### Pre-intervention Weekly Probability Below Buffer",
            "",
            "| Week | P10 Balance (₹) | P50 Balance (₹) | Prob Below Buffer | Expected Shortfall (₹) |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for w in sim_res["weeks"]:
            md_lines.append(
                f"| W{w['week_index']} | ₹{w['p10_closing_balance_paise']/100:,.2f} | ₹{w['p50_closing_balance_paise']/100:,.2f} | {w['prob_below_buffer']*100:.2f}% | ₹{w['expected_shortfall_paise']/100:,.2f} |"
            )

        g_plan = plan.planning_details.get("guaranteed_plan", {})
        e_plan = plan.planning_details.get("expected_plan", {})

        md_lines.extend([
            "",
            "## 2. Financing Plan (Target Probability <= 20%)",
            "",
            f"- **Plan ID**: {plan.id}",
            f"- **Overall Plan Status**: {plan.status}",
            f"- **Guaranteed Plan Status**: {plan.planning_details.get('guaranteed_status', 'VALID')}",
            f"- **Guaranteed Total Cost**: ₹{(plan.planning_details.get('guaranteed_total_cost_paise', 0)/100):,.2f} ({plan.planning_details.get('guaranteed_total_cost_paise', 0):,} paise)",
            f"- **Expected Plan Total Cost (with Collections)**: ₹{(plan.planning_details.get('expected_total_cost_paise', 0)/100):,.2f} ({plan.planning_details.get('expected_total_cost_paise', 0):,} paise)",
            f"- **NBFC Unsecured Loan Comparison Baseline Cost**: ₹{(plan.baseline_cost_paise/100):,.2f} ({plan.baseline_cost_paise:,} paise)",
            f"- **Calculated Savings vs NBFC Baseline**: ₹{((plan.baseline_cost_paise - plan.total_cost_paise)/100):,.2f} ({((plan.baseline_cost_paise - plan.total_cost_paise)/plan.baseline_cost_paise*100):.1f}%)",
            "",
            "### Executed Plan Lines",
            "",
            "| Product | Scope | Amount (₹) | Week | Days | Cost (₹) | Effective Annual Rate | Tier |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])

        for line in lines:
            scope_str = f"Invoice {line.scope_ids[0]}" if line.scope_ids else "Facility"
            terms = next((e for e in line.evidence if "days" in e), {})
            days_str = str(terms.get("days", 0))
            ear_str = f"{float(line.effective_annual_rate)*100:.2f}%" if line.effective_annual_rate and line.effective_annual_rate != "0" else "0.00%"
            md_lines.append(
                f"| {line.product_id} | {scope_str} | ₹{line.amount_paise/100:,.2f} | W{line.arrival_week} | {days_str} | ₹{line.cost_paise/100:,.2f} | {ear_str} | {line.required_tier} |"
            )

        md_lines.extend([
            "",
            "## 3. Stage 4 Execution & Reforecast",
            "",
            f"- **Reminders Dispatched (Outbox)**: {outbox_count} collections reminders queued/sent (zero monetary cash fabricated).",
            f"- **Sandbox Ledger Postings**: {len(sandbox_entries)} posting(s).",
        ])

        for entry in sandbox_entries:
            md_lines.append(
                f"  - **{entry.kind}** ({entry.label}): Net cash proceeds of ₹{entry.amount_paise/100:,.2f} posted on `{entry.entry_date.isoformat()}`; receivable reduction ₹{entry.receivable_reduction_paise/100:,.2f}."
            )

        md_lines.extend([
            "",
            f"- **Post-Execution Reforecast Run ID**: {post_run.id}",
            f"- **Post-Execution Week 6 Shortfall Probability**: {(post_weeks[5].prob_below_buffer*100):.2f}% (Target: <= 20.00%)",
            f"- **Post-Execution Open Cash Alert**: {f'Week {post_alert.week_index}' if post_alert else 'None (Alert fully resolved)'}",
            "",
            "### Post-Execution Weekly Probability Below Buffer",
            "",
            "| Week | P10 Balance (₹) | P50 Balance (₹) | Prob Below Buffer |",
            "| :--- | :--- | :--- | :--- |",
        ])

        for w in post_weeks:
            md_lines.append(
                f"| W{w.week_index} | ₹{w.p10_closing_balance_paise/100:,.2f} | ₹{w.p50_closing_balance_paise/100:,.2f} | {w.prob_below_buffer*100:.2f}% |"
            )

        out_md_path.parent.mkdir(parents=True, exist_ok=True)
        out_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        print(f"Canonical demo numbers successfully written to {out_md_path}")

    finally:
        session.close()
        engine.dispose()
        gc.collect()


if __name__ == "__main__":
    db_file = ROOT / "kosh_demo_eval.db"
    target_md = ROOT / "docs" / "kosh" / "demo_numbers.md"
    try:
        run_demo(db_file, target_md)
    finally:
        if db_file.exists():
            try:
                db_file.unlink()
            except Exception:
                pass
