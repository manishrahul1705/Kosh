"""Typed cash proposals; only the owner confirms their inclusion."""
from datetime import date
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictInt,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_edit,require_seller_owner
from app.database.kosh_models import KoshCashEvent
from app.database.session import reserve_sqlite_writer
from app.audit.ledger import append_event
from app.utils.dates import utcnow
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/cash-events",tags=["kosh-cash-events"])
class CashEventIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    event_type:Literal["EXPECTED_RECEIVABLE","SCHEDULED_PAYABLE","COST_CHANGE","FINANCING_NEED"]
    source_module:Literal["sales","procurement","pricing","collections","customer_intelligence","revenue","tender_to_cash","operations"]
    evidence_ref:str=Field(min_length=1,max_length=160)
    event_date:date
    amount_paise:StrictInt=Field(ge=0)
def out(row):return {c.name:getattr(row,c.name) for c in row.__table__.columns}
def record(db,seller_id,access,action,payload,tier="T1"):
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action=action,tier=tier,payload=payload,policy_decision="ALLOW");db.commit()
@router.get("")
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    items=[out(row) for row in db.scalars(select(KoshCashEvent).where(KoshCashEvent.seller_id==seller_id).order_by(KoshCashEvent.id))]
    record(db,seller_id,access,"cash_events.read",{},"T0");return {"items":items,"role":access.role}
@router.post("")
def propose(seller_id:int,payload:CashEventIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True)
    row=KoshCashEvent(seller_id=seller_id,created_by_user_id=access.user_id,status="PROPOSED",**payload.model_dump());db.add(row);db.flush()
    record(db,seller_id,access,"cash_event.propose",{"id":row.id,"event_type":row.event_type,"amount_paise":row.amount_paise});return out(row)
@router.post("/{event_id}/confirm")
def confirm(seller_id:int,event_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True)
    row=db.scalar(select(KoshCashEvent).where(KoshCashEvent.id==event_id,KoshCashEvent.seller_id==seller_id).with_for_update())
    if row is None:raise HTTPException(404,"Cash event not found")
    if row.status not in {"PROPOSED","CONFIRMED"}:raise HTTPException(409,"Rejected event cannot be confirmed")
    row.status="CONFIRMED";row.confirmed_at=row.confirmed_at or utcnow();row.confirmed_by_user_id=access.user_id
    record(db,seller_id,access,"cash_event.confirm",{"id":row.id,"amount_paise":row.amount_paise});return out(row)
