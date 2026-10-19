"""Seller-scoped consent lifecycle with audit events."""
from datetime import date,datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.audit.ledger import append_event
from app.database.kosh_models import KoshConsentArtifact
from app.utils.dates import to_utc_naive,utcnow

DATA_TYPES=frozenset({"BANK_STATEMENT","SALES_INVOICES","PURCHASE_BILLS","BOOKS_EXPORT","BUSINESS_PROFILE"})

def create_consent(session:Session,*,seller_id:int,granted_by_user_id:int,purpose:str,data_types:list[str],data_from:date,data_to:date,expires_at:datetime)->KoshConsentArtifact:
    if expires_at.tzinfo is not None:expires_at=to_utc_naive(expires_at)
    if not data_types or not set(data_types)<=DATA_TYPES:raise ValueError("INVALID_CONSENT_DATA_TYPE")
    if data_to<data_from or expires_at<=utcnow():raise ValueError("INVALID_CONSENT_PERIOD")
    row=KoshConsentArtifact(seller_id=seller_id,granted_by_user_id=granted_by_user_id,purpose=purpose,data_types=sorted(set(data_types)),data_from=data_from,data_to=data_to,expires_at=expires_at,status="ACTIVE")
    session.add(row);session.flush();append_event(session,seller_id=seller_id,actor_type="HUMAN",actor_id=str(granted_by_user_id),action="consent.create",tier="T0_READ",payload={"consent_id":row.id,"data_types":row.data_types,"expires_at":expires_at},policy_decision="ALLOW");session.commit();return row

def get_active_consent(session:Session,seller_id:int,data_type:str,at:datetime|None=None)->KoshConsentArtifact|None:
    at=at or utcnow()
    if at.tzinfo is not None:at=to_utc_naive(at)
    rows=session.scalars(select(KoshConsentArtifact).where(KoshConsentArtifact.seller_id==seller_id,KoshConsentArtifact.status=="ACTIVE").order_by(KoshConsentArtifact.id.desc())).all()
    for row in rows:
        if row.expires_at<=at:row.status="EXPIRED";continue
        if data_type in row.data_types:return row
    return None

def revoke_consent(session:Session,*,seller_id:int,artifact_id:int,actor_user_id:int)->KoshConsentArtifact:
    row=session.scalar(select(KoshConsentArtifact).where(KoshConsentArtifact.id==artifact_id,KoshConsentArtifact.seller_id==seller_id))
    if row is None:raise LookupError("CONSENT_NOT_FOUND")
    row.status="REVOKED";row.revoked_at=utcnow();append_event(session,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_user_id),action="consent.revoke",tier="T0_READ",payload={"consent_id":row.id},policy_decision="ALLOW");session.commit();return row
