"""Exact purpose/recipient/field consent for future outbound data packs."""
from sqlalchemy import select
from app.audit.ledger import append_event
from app.database.session import reserve_sqlite_writer
from app.database.kosh_models import KoshSharingConsent
from app.lending.catalogue import load_catalogue
from app.utils.dates import utcnow,to_utc_naive

PURPOSES={"TREDS_FINANCE","OD_DRAWDOWN","LOAN_APPLICATION","SHARE_DATA_PACK"}
FIELDS={"invoice_id","amount_paise","due_date","invoice_number","invoice_date","buyer_name","gstin","udyam_number","last_fy_turnover_paise","incorporation_date","cash_report_pdf","forecast","plan","options","audit_hash"}

def active(db,*,seller_id,purpose,recipient_id,fields,at=None):
    at=to_utc_naive(at) if at is not None else utcnow()
    rows=db.scalars(select(KoshSharingConsent).where(KoshSharingConsent.seller_id==seller_id,KoshSharingConsent.status=="ACTIVE",KoshSharingConsent.purpose==purpose,KoshSharingConsent.recipient_id==recipient_id,KoshSharingConsent.expires_at>at).order_by(KoshSharingConsent.id.desc())).all()
    return next((row for row in rows if set(fields)<=set(row.fields)),None)

def grant(db,*,seller_id,actor_id,purpose,recipient_id,fields,expires_at):
    expires_at=to_utc_naive(expires_at)
    if purpose not in PURPOSES:raise ValueError("INVALID_SHARING_PURPOSE")
    if recipient_id not in {product["id"] for product in load_catalogue()}:raise ValueError("UNKNOWN_RECIPIENT")
    if not fields or not set(fields)<=FIELDS:raise ValueError("INVALID_SHARING_FIELDS")
    if expires_at<=utcnow():raise ValueError("CONSENT_EXPIRY_MUST_BE_FUTURE")
    reserve_sqlite_writer(db,renew_read=True)
    row=KoshSharingConsent(seller_id=seller_id,granted_by_user_id=actor_id,purpose=purpose,recipient_id=recipient_id,fields=sorted(set(fields)),expires_at=expires_at,status="ACTIVE")
    db.add(row);db.flush()
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="sharing.consent.grant",tier="T1",payload={"consent_id":row.id,"purpose":purpose,"recipient_id":recipient_id,"fields":row.fields,"expires_at":expires_at},policy_decision="ALLOW")
    return row

def revoke(db,*,seller_id,consent_id,actor_id):
    reserve_sqlite_writer(db,renew_read=True)
    row=db.scalar(select(KoshSharingConsent).where(KoshSharingConsent.id==consent_id,KoshSharingConsent.seller_id==seller_id).with_for_update())
    if row is None:raise LookupError("CONSENT_NOT_FOUND")
    row.status="REVOKED";row.revoked_at=utcnow()
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="sharing.consent.revoke",tier="T1",payload={"consent_id":row.id},policy_decision="ALLOW")
    return row

def out(row):
    return {"id":row.id,"seller_id":row.seller_id,"purpose":row.purpose,"recipient_id":row.recipient_id,"fields":row.fields,"expires_at":row.expires_at.isoformat()+"Z","status":row.status if row.status!="ACTIVE" or row.expires_at>utcnow() else "EXPIRED","revoked_at":row.revoked_at.isoformat()+"Z" if row.revoked_at else None}
