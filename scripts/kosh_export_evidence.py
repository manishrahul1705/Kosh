"""Reproduce the offline walkthrough on a disposable database and export safe evidence."""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAFE_ENV = {
    "SCHEDULER_ENABLED": "false", "AUTO_MIGRATE": "false",
    "COLLECT_ON_STARTUP": "false", "STARTUP_RECOVERY_ENABLED": "false",
    "APP_ENV": "development", "KOSH_AS_OF_DATE": "2026-10-13",
}


def assert_safe(text: str) -> None:
    """Fail closed on credentials, delivery payloads and unmasked challenge codes."""
    forbidden = r'"(?:code|otp|otp_code|token|approval_token|access_token|refresh_token|secret|password|api_key|authorization|code_hash|encrypted_payload)"\s*:'
    if re.search(forbidden, text, re.I):
        raise ValueError("Credential-bearing field in evidence")
    if re.search(r'\beyJ[A-Za-z0-9_-]+\.(?:[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|[a-f0-9]{64})\b|Bearer\s+\S+|-----BEGIN .*PRIVATE KEY', text):
        raise ValueError("Credential material in evidence")
    if re.search(r'(?:OTP|one.time|verification)\s*(?:code)?\s*[:=]\s*[0-9]{6}\b', text, re.I):
        raise ValueError("Unmasked OTP in evidence")


def write_records(path: Path, records) -> None:
    from app.audit.ledger import canonical_json
    text = "".join(canonical_json(record) + "\n" for record in records)
    assert_safe(text)
    path.write_text(text, encoding="utf-8")


def export_evidence(db, out: Path, before: dict, after, security_results) -> None:
    from sqlalchemy import select
    from app.audit.verify import verify_chain
    from app.database.kosh_models import (
        KoshAuditEntry, KoshSandboxOutbox, KoshSandboxLedgerEntry,
        KoshActionIntent, KoshSandboxInbox,
    )

    out.mkdir(parents=True, exist_ok=True)
    # Invoke the actual proposal route, with an explicit seeded owner context. No
    # HTTP server or external transport is started. Capture its real 403 detail.
    from fastapi import HTTPException
    from app.api.actions import propose
    from app.api.seller_authorization import AuthorizedSeller
    from app.policy.controls import editable_control
    from app.database.auth_models import SellerMembership
    intent = db.scalar(select(KoshActionIntent).order_by(KoshActionIntent.id))
    if intent is None:
        raise ValueError("Walkthrough did not create intents")
    owner = db.scalar(select(SellerMembership).where(
        SellerMembership.seller_id == intent.seller_id, SellerMembership.role == "OWNER"))
    access = AuthorizedSeller(user_id=owner.user_id, seller_id=intent.seller_id, role="OWNER")
    route_attempts = []
    def denied_proposal(label, payload, expected):
        try:
            propose(intent.seller_id, payload, db, access)
        except HTTPException as exc:
            if exc.status_code != 403 or expected not in exc.detail["rule_ids"]:
                raise
            route_attempts.append({"attempt": label, "status_code": exc.status_code,
                                   "detail": exc.detail, "basis": "proposal route invocation"})
        else:
            raise ValueError(f"Security attempt unexpectedly allowed: {label}")
    denied_proposal("document-origin payment", {"source": "DOCUMENT", "action_type": "PAYMENT",
                    "amount_paise": 48_000_000, "payee": "UNTRUSTED"}, "DOCUMENT_PARAMETERS")
    control = editable_control(db, intent.seller_id)
    previous = control.kill_switch
    try:
        control.kill_switch = True
        db.commit()
        denied_proposal("kill switch", {"action_type": "OD_DRAWDOWN"}, "KILL_SWITCH")
    finally:
        control.kill_switch = previous
        db.commit()

    # The least-cost seed-42 plan only funds TReDS. Exercise the separate
    # collections path as well, so the evidence includes a real approved reminder.
    from app.api.collections import draft, DraftIn
    from app.actions.addons import create_from_draft
    from app.actions.approvals import approve, recheck, ActionError
    from app.actions.execution import execute
    from app.database.kosh_models import KoshInvoice
    invoice = db.scalar(select(KoshInvoice).where(
        KoshInvoice.seller_id == intent.seller_id, KoshInvoice.direction == "RECEIVABLE",
        KoshInvoice.status == "OPEN").order_by(KoshInvoice.due_date, KoshInvoice.id))
    if invoice is None:
        raise ValueError("No open receivable available for reminder evidence")
    drafted = draft(intent.seller_id, DraftIn(invoice_id=invoice.id), db, access)
    reminder = create_from_draft(db, seller_id=intent.seller_id,
                                 draft_id=drafted["id"], creator_id=owner.user_id)
    db.commit()
    _, approval = approve(db, seller_id=intent.seller_id,
                          intent_id=reminder.id, actor_id=owner.user_id)
    db.commit()
    # Exercise the switch against a valid, approved action, not just an invalid
    # proposal. Restore policy, revoke the old approval via recheck and reapprove.
    try:
        control.kill_switch = True
        db.commit()
        try:
            execute(db, seller_id=intent.seller_id, intent_id=reminder.id,
                    actor_id=owner.user_id, token=approval)
        except ActionError as exc:
            if exc.status_code != 403 or exc.rule != "KILL_SWITCH":
                raise
            db.commit()
            route_attempts.append({"attempt": "approved reminder under kill switch",
                                   "status_code": exc.status_code,
                                   "detail": {"rule_ids": [exc.rule], "reason": str(exc)},
                                   "basis": "approved execution ActionError"})
        else:
            raise ValueError("Kill switch allowed an approved action to execute")
    finally:
        control.kill_switch = previous
        db.commit()
    recheck(db, seller_id=intent.seller_id, intent_id=reminder.id, actor_id=owner.user_id)
    db.commit()
    _, approval = approve(db, seller_id=intent.seller_id,
                          intent_id=reminder.id, actor_id=owner.user_id)
    db.commit()
    settlement = execute(db, seller_id=intent.seller_id, intent_id=reminder.id,
                         actor_id=owner.user_id, token=approval)
    db.commit()
    if (settlement.status != "SETTLED" or
            settlement.result["before_probabilities"] != settlement.result["after_probabilities"]):
        raise ValueError("Reminder must settle without inventing a cash receipt")
    def rows(model, *fields):
        return [{field: getattr(row, field) for field in fields}
                for row in db.scalars(select(model).order_by(model.id))]

    messages = rows(KoshSandboxOutbox, "id", "intent_id", "channel", "recipient_ref", "body", "status")
    # Never decrypt the delivery inbox: even ciphertext and code hashes stay private.
    for row in db.scalars(select(KoshSandboxInbox).order_by(KoshSandboxInbox.id)):
        messages.append({"kind": row.kind, "intent_id": row.intent_id,
                         "delivery": "SANDBOX", "message": "OTP delivery [MASKED]"})
    write_records(out / "sandbox_outbox.jsonl", messages)
    write_records(out / "sandbox_ledger.jsonl", rows(
        KoshSandboxLedgerEntry, "id", "execution_id", "kind", "entry_date", "amount_paise",
        "invoice_id", "receivable_reduction_paise", "status", "label"))

    audit = list(db.scalars(select(KoshAuditEntry).order_by(KoshAuditEntry.sequence)))
    events = []
    states = {"intent.propose": "PROPOSED", "addon.intent.propose": "PROPOSED",
              "intent.approve": "APPROVED", "intent.executing": "EXECUTING",
              "intent.succeeded": "SUCCEEDED", "addon.intent.succeeded": "SUCCEEDED"}
    for row in audit:
        if row.action.startswith(("intent.", "addon.intent.", "security.", "execution.", "approval.")):
            event = {"sequence": row.sequence, "action": row.action, "tier": row.tier,
                     "decision": row.policy_decision, "payload": row.payload}
            if row.action in states:
                event["state"] = states[row.action]
            if (row.policy_decision == "DENY" and
                    set(row.payload.get("rule_ids", [])) & {"OTP_REQUIRED", "TOKEN_REPLAY", "PARAMS_TAMPERED"}):
                event["status_code"] = 403
                event["basis"] = "asserted ActionError from walkthrough"
            events.append(event)
    for row in db.scalars(select(KoshActionIntent).order_by(KoshActionIntent.id)):
        events.append({"intent_id": row.id, "final_status": row.status, "tier": row.tier})
    # Pure policy evaluations have no HTTP response; label their actual basis explicitly.
    events.extend({"security_check": item, "basis": "walkthrough assertion"}
                  for item in security_results)
    events.extend(route_attempts)
    write_records(out / "action_intents.jsonl", events)
    write_records(out / "audit_chain.jsonl", (
        {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for row in audit))
    result = verify_chain(db)
    if not result.valid:
        raise ValueError("Audit chain is invalid")
    # Run the submission's verifier against the same throwaway database before
    # cleanup, and retain its actual output rather than synthesizing a CLI result.
    verified = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_audit_chain.py")],
        cwd=ROOT, env={**os.environ, **SAFE_ENV,
                       # SQLAlchemy's rendered URL percent-escapes the Windows
                       # drive colon; Settings treats that as a relative path.
                       "DATABASE_URL": f"sqlite:///{Path(db.get_bind().url.database).as_posix()}"},
        capture_output=True, text=True,
    )
    if verified.returncode:
        raise RuntimeError(f"Audit verifier failed:\n{verified.stdout}\n{verified.stderr}")
    if verified.stdout.strip() != f"VALID, {result.entries} entries":
        raise ValueError("Audit verifier output does not match exported chain")
    (out / "audit_verify.txt").write_text(verified.stdout, encoding="utf-8")
    write_records(out / "forecast_before_after.json", [{
        "seed": 42, "as_of_date": "2026-10-13", "n_paths": 2000,
        "before": before["weeks"],
        "after": [{field: getattr(week, field) for field in (
            "week_index", "prob_below_buffer", "p10_closing_balance_paise",
            "p50_closing_balance_paise", "p90_closing_balance_paise")}
                  for week in after],
    }])
    for path in out.iterdir():
        if path.is_file():
            assert_safe(path.read_text(encoding="utf-8"))


def main() -> None:
    os.environ.update(SAFE_ENV)
    # TemporaryDirectory removes the database, generated borrower files and private inbox.
    with tempfile.TemporaryDirectory(prefix="kosh-evidence-") as name:
        work = Path(name)
        os.environ["DATABASE_URL"] = f"sqlite:///{(work / 'demo.db').as_posix()}"
        from scripts.kosh_demo_numbers import run_demo
        run_demo(work / "demo.db", work / "demo_numbers.md", work_root=work,
                 evidence_dir=ROOT / "docs/kosh/evidence")


if __name__ == "__main__":
    main()
