"""End-to-end integration test verifying the 5-minute judge demo walkthrough via API."""
from __future__ import annotations
import re
from datetime import date
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import create_app
from scripts.kosh_generate_demo import generate
from scripts.kosh_seed_demo import seed


def test_full_demo_walkthrough_api(settings, session_factory, source, tmp_path):
    as_of = date(2026, 10, 13)
    data_dir = tmp_path / "demo_data"
    storage_dir = tmp_path / "storage"

    # Step 0: Setup demo database with seed 42
    generate(seed=42, out=data_dir, as_of=as_of)
    db_url = settings.resolved_database_url
    seed(database_url=db_url, data_dir=data_dir, storage=storage_dir)

    app = create_app(
        settings.model_copy(update={"dev_login_enabled": True, "kosh_as_of_date": "2026-10-13"}),
        session_factory=session_factory,
        collector_factory=source,
    )

    with TestClient(app) as client:
        # Step 1: Dev Login with arbitrary email
        login_res = client.post("/api/dev/login", json={"email": "judge_walkthrough@kosh.local"})
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Verify Meenakshi Precision Components accessible
        sellers_res = client.get("/api/sellers", headers=headers)
        assert sellers_res.status_code == 200
        sellers = sellers_res.json()
        demo_seller = next(s for s in sellers if s["name"] == "Meenakshi Precision Components")
        seller_id = demo_seller["id"]

        # Step 2: Connect - Ingested documents & poisoned invoice quarantine
        docs_res = client.get(f"/api/kosh/sellers/{seller_id}/documents", headers=headers)
        assert docs_res.status_code == 200
        docs = docs_res.json()
        assert len(docs) == 18
        poisoned = [d for d in docs if "poisoned" in d["original_filename"]]
        assert len(poisoned) == 2
        for p in poisoned:
            assert p["status"] == "REVIEW"
            assert "INSTRUCTION_TEXT_DETECTED" in (p["status_reason"] or "")

        # Step 3: Ledger Snapshot - Verified Payables vs Held for Review
        ledger_res = client.get(f"/api/kosh/sellers/{seller_id}/ledger", headers=headers)
        assert ledger_res.status_code == 200
        totals = ledger_res.json()["totals"]
        assert totals["open_payables_paise"] == 380_397_322
        assert totals["held_for_review_payables_paise"] == 96_000_000
        assert totals["review_count"] == 2
        assert totals["latest_bank_balance_paise"] == 249_731_842

        # Step 4: Baseline 13-week Forecast & Alert
        run_res = client.post(
            f"/api/kosh/sellers/{seller_id}/forecast/run",
            json={"n_paths": 2000, "seed": 42, "include_forecast_sales": True, "include_addon_events": True},
            headers=headers,
        )
        assert run_res.status_code == 200

        fc_res = client.get(f"/api/kosh/sellers/{seller_id}/forecast/latest", headers=headers)
        assert fc_res.status_code == 200
        fc_data = fc_res.json()
        assert len(fc_data["weeks"]) == 13
        assert fc_data["alert"]["week_index"] == 6
        assert abs(fc_data["alert"]["probability"] - 0.7995) < 0.05

        # Step 5: Financing Catalogue Evaluation (8 products)
        eval_res = client.post(f"/api/kosh/sellers/{seller_id}/financing/evaluate", headers=headers)
        assert eval_res.status_code == 200
        options_res = client.get(f"/api/kosh/sellers/{seller_id}/financing/options", headers=headers)
        assert options_res.status_code == 200
        options = {item["product_id"]: item for item in options_res.json()["items"]}
        assert options["TREDS_INVOICE_DISCOUNTING"]["status"] == "MATCHED"
        assert options["BANK_OD_DRAWDOWN"]["status"] == "MATCHED"
        assert options["MUDRA_LOAN"]["status"] == "REVIEW_REQUIRED"
        assert options["CGTMSE_BACKED_WC_LOAN"]["status"] == "REVIEW_REQUIRED"

        # Step 6: Create Plan (target 0.20)
        plan_create = client.post(
            f"/api/kosh/sellers/{seller_id}/plans",
            json={"target_probability": 0.20, "target_scope": "ALL_WEEKS"},
            headers=headers,
        )
        assert plan_create.status_code == 200
        plan_id = plan_create.json()["plan_id"]

        plan_res = client.get(f"/api/kosh/sellers/{seller_id}/plans/latest", headers=headers)
        assert plan_res.status_code == 200
        plan_data = plan_res.json()
        assert plan_data["status"] == "VALID"
        assert len(plan_data["lines"]) >= 1
        treds_line = next(l for l in plan_data["lines"] if "TREDS" in l["product_id"].upper())
        assert treds_line["amount_paise"] > 0
        assert treds_line["cost_paise"] > 0

        # Verify savings vs NBFC baseline (~81.7%)
        saving = plan_data["baseline_cost_paise"] - plan_data["total_cost_paise"]
        savings_pct = (saving / plan_data["baseline_cost_paise"]) * 100
        assert savings_pct > 80.0

        # Step 7: Approvals & OTP Step-Up Flow
        intent_res = client.post(
            f"/api/kosh/sellers/{seller_id}/actions/intents",
            json={"plan_line_id": treds_line["id"]},
            headers=headers,
        )
        assert intent_res.status_code == 200
        intent_id = intent_res.json()["id"]

        # Step 7a: Creator attempts to approve self - blocked by four-eyes policy (SECOND_APPROVER)
        otp_req_c = client.post(f"/api/kosh/sellers/{seller_id}/actions/intents/{intent_id}/otp", headers=headers)
        assert otp_req_c.status_code == 200
        inbox_c = client.get(f"/api/kosh/sellers/{seller_id}/sandbox/inbox", headers=headers).json()["items"]
        otp_c = next(m for m in inbox_c if m.get("intent_id") == intent_id)["payload"]["code"]

        self_approve = client.post(
            f"/api/kosh/sellers/{seller_id}/actions/intents/{intent_id}/approve",
            json={"otp_code": str(otp_c)},
            headers=headers,
        )
        assert self_approve.status_code == 403
        assert "SECOND_APPROVER" in self_approve.json()["detail"]["rule_ids"]

        # Step 7b: Second approver signs in to approve with OTP
        approver_login = client.post("/api/dev/login", json={"email": "demo@kosh.local"})
        assert approver_login.status_code == 200
        approver_token = approver_login.json()["access_token"]
        approver_headers = {"Authorization": f"Bearer {approver_token}"}

        # Request OTP for T3 by second approver
        otp_req = client.post(f"/api/kosh/sellers/{seller_id}/actions/intents/{intent_id}/otp", headers=approver_headers)
        assert otp_req.status_code == 200

        # Retrieve simulated OTP from sandbox inbox
        inbox_res = client.get(f"/api/kosh/sellers/{seller_id}/sandbox/inbox", headers=approver_headers)
        assert inbox_res.status_code == 200
        items = inbox_res.json()["items"]
        assert len(items) > 0
        otp_item = next(m for m in items if m.get("intent_id") == intent_id)
        otp_code = str(otp_item["payload"]["code"])

        # Approve with OTP
        approve_res = client.post(
            f"/api/kosh/sellers/{seller_id}/actions/intents/{intent_id}/approve",
            json={"otp_code": otp_code},
            headers=approver_headers,
        )
        assert approve_res.status_code == 200
        approval_token = approve_res.json()["approval_token"]

        # Execute in sandbox
        exec_res = client.post(
            f"/api/kosh/sellers/{seller_id}/actions/intents/{intent_id}/execute",
            json={"approval_token": approval_token},
            headers=approver_headers,
        )
        assert exec_res.status_code == 200

        # Step 8: Re-forecast after intervention
        re_run = client.post(
            f"/api/kosh/sellers/{seller_id}/forecast/run",
            json={"n_paths": 2000, "seed": 42, "include_forecast_sales": True, "include_addon_events": True},
            headers=headers,
        )
        assert re_run.status_code == 200
        post_fc = client.get(f"/api/kosh/sellers/{seller_id}/forecast/latest", headers=headers).json()
        week6 = post_fc["weeks"][5]
        # Shortfall probability dropped significantly to <= 20%
        assert week6["prob_below_buffer"] <= 0.20
        for w in post_fc["weeks"]:
            assert w["prob_below_buffer"] <= 0.20

        # Step 9: Attack resistance - blocked payment from poisoned document
        attack_res = client.post(
            f"/api/kosh/sellers/{seller_id}/actions/intents",
            json={"source": "DOCUMENT", "action_type": "PAYMENT", "amount_paise": 48_000_000, "payee": "XXXX"},
            headers=headers,
        )
        assert attack_res.status_code == 403

        # Step 10: Kill Switch toggle
        ks_on = client.post(f"/api/kosh/sellers/{seller_id}/policy/kill-switch", json={"enabled": True, "scope": "SELLER"}, headers=headers)
        assert ks_on.status_code == 200
        # When kill switch is on, proposing an intent is blocked
        blocked_prop = client.post(
            f"/api/kosh/sellers/{seller_id}/actions/intents",
            json={"plan_line_id": treds_line["id"]},
            headers=headers,
        )
        assert blocked_prop.status_code in (400, 403, 409)

        # Restore kill switch
        ks_off = client.post(f"/api/kosh/sellers/{seller_id}/policy/kill-switch", json={"enabled": False, "scope": "SELLER"}, headers=headers)
        assert ks_off.status_code == 200

        # Step 11: Audit Chain Verification
        audit_verify = client.get(f"/api/kosh/sellers/{seller_id}/audit/verify", headers=headers)
        assert audit_verify.status_code == 200
        assert audit_verify.json()["valid"] is True
        assert audit_verify.json()["broken_at_sequence"] is None
