"""Seller-authorized consent endpoints."""
from datetime import date,datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_approval,require_seller_read
from app.consent.service import create_consent,revoke_consent
from app.database.kosh_models import KoshConsentArtifact

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/consents",tags=["kosh-consents"])
class ConsentIn(BaseModel):
    purpose:str;data_types:list[str];data_from:date;data_to:date;expires_at:datetime

def out(row):return {"id":row.id,"seller_id":row.seller_id,"purpose":row.purpose,"data_types":row.data_types,"data_from":row.data_from,"data_to":row.data_to,"expires_at":row.expires_at,"status":row.status,"revoked_at":row.revoked_at}

@router.post("")
def create(seller_id:int,payload:ConsentIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    try:return out(create_consent(db,seller_id=seller_id,granted_by_user_id=access.user_id,**payload.model_dump()))
    except ValueError as exc:raise HTTPException(422,detail=str(exc)) from exc

@router.get("")
def list_consents(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    return [out(x) for x in db.scalars(select(KoshConsentArtifact).where(KoshConsentArtifact.seller_id==seller_id).order_by(KoshConsentArtifact.id.desc()))]

@router.post("/{consent_id}/revoke")
def revoke(seller_id:int,consent_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    try:return out(revoke_consent(db,seller_id=seller_id,artifact_id=consent_id,actor_user_id=access.user_id))
    except LookupError as exc:raise HTTPException(404,detail=str(exc)) from exc
