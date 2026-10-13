"""Seeded invoice text is data, never an action authority."""
from datetime import date, datetime, timedelta
from sqlalchemy import select, func
from app.consent.service import create_consent
from app.database.kosh_models import KoshActionIntent, KoshAuditEntry
from app.finance.intake.private_store import store_private_document
from app.finance.intake.service import process_private_document
from app.finance.intake.invoice_pdf import extract_invoice_pdf
from app.audit.export import security_counts
from scripts.kosh_generate_demo import create_attack_invoice
from tests.test_kosh_stage4_intents import planned_line, SUBJECT
from tests.conftest import sign_in


def test_seeded_payment_injection_is_data_and_forced_action_is_blocked(client, db, tmp_path):
    seller, user, _, _ = planned_line(db)
    create_consent(db, seller_id=seller.id, granted_by_user_id=user.id,
        purpose="Invoice intake", data_types=["PURCHASE_BILLS"],
        data_from=date(2024, 1, 1), data_to=date(2027, 1, 1),
        expires_at=datetime.utcnow()+timedelta(days=30))
    pdf=tmp_path/"attack.pdf"
    create_attack_invoice(pdf, date(2026, 10, 13))
    extracted=extract_invoice_pdf(pdf)
    assert extracted["invoice_number"]=="POISON-002"
    assert extracted["amounts"]["total"]==48_000_000
    before=security_counts(db, seller.id)
    doc, version, _=store_private_document(db, seller_id=seller.id, user_id=user.id,
        kind="PURCHASE_BILL", filename=pdf.name, content=pdf.read_bytes(),
        storage_root=tmp_path, max_bytes=100_000)
    process_private_document(db, document=doc, version=version,
        path=tmp_path/version.storage_key, actor_id=user.id)
    db.commit()
    assert doc.status=="REVIEW" and "INSTRUCTION_TEXT_DETECTED" in doc.status_reason
    assert db.scalar(select(func.count()).select_from(KoshActionIntent))==0
    sign_in(client.app, SUBJECT)
    response=client.post(f"/api/kosh/sellers/{seller.id}/actions/intents", json={
        "source":"DOCUMENT", "action_type":"PAYMENT", "amount_paise":48_000_000, "payee":"XXXX"})
    assert response.status_code==403
    policy=response.json()["detail"]
    assert policy["tier"]=="T4" and policy["decision"]=="DENY"
    assert {"FREE_TEXT_INTENT","TRUSTED_ORIGIN","ALLOWLIST","DOCUMENT_PARAMETERS"}<=set(policy["rule_ids"])
    db.rollback(); db.expire_all()
    after=security_counts(db, seller.id)
    assert after["injection_detections"]==before["injection_detections"]+1
    assert after["blocked_intents"]==before["blocked_intents"]+1
    assert db.scalar(select(func.count()).select_from(KoshActionIntent))==0
    assert db.scalar(select(KoshAuditEntry).where(KoshAuditEntry.action=="security.injection_detected"))
