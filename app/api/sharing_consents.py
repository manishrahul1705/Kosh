"""Authorized consent grants and revocations for scoped lender data sharing."""
from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_approval,require_seller_read
from app.audit.ledger import append_event
from app.database.kosh_models import KoshSharingConsent
from app.consent.sharing import grant,revoke,out

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/consents/sharing",tags=["kosh-sharing-consents"])

class SharingIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    purpose:str=Field(min_length=1,max_length=48)
    recipient_id:str=Field(min_length=1,max_length=64)
    fields:list[str]
    expires_at:datetime

@router.post("")
def create(seller_id:int,payload:SharingIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    try:row=grant(db,seller_id=seller_id,actor_id=access.user_id,**payload.model_dump())
    except ValueError as exc:raise HTTPException(422,str(exc))
    db.commit();return out(row)

@router.get("")
def list_sharing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.scalars(select(KoshSharingConsent).where(KoshSharingConsent.seller_id==seller_id).order_by(KoshSharingConsent.id.desc())).all()
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="sharing.consents.read",tier="T0",payload={},policy_decision="ALLOW");db.commit()
    return {"seller_id":seller_id,"items":[out(row) for row in rows]}

@router.post("/{consent_id}/revoke")
def revoke_sharing(seller_id:int,consent_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    try:row=revoke(db,seller_id=seller_id,consent_id=consent_id,actor_id=access.user_id)
    except LookupError as exc:raise HTTPException(404,str(exc))
    db.commit();return out(row)
