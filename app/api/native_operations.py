"""Native sales, PO, RFQ and material-price proposals with tenant-owned evidence."""
from datetime import date
from decimal import Decimal,ROUND_HALF_UP
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictInt,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_edit,require_seller_owner
from app.database.kosh_models import KoshOperationRecord,KoshCashEvent,KoshCounterparty,KoshAddonDraft
from app.database.session import reserve_sqlite_writer
from app.audit.ledger import append_event
from app.policy.internal import gate
from app.actions.addons import draft_hash,create_from_draft
from app.actions.read import out
from app.utils.dates import utcnow
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/operations",tags=["kosh-operations"])
MARKET_SAMPLE=[{"material_code":"STEEL","change_percent":"8","source":"Bundled fictional offline sample","verified_market_fact":False},{"material_code":"ALUMINIUM","change_percent":"-3","source":"Bundled fictional offline sample","verified_market_fact":False}]
class StrictInput(BaseModel):model_config=ConfigDict(extra="forbid")
class OrderIn(StrictInput):
    direction:Literal["SALE","PO"]
    counterparty_id:StrictInt=Field(gt=0)
    amount_paise:StrictInt=Field(gt=0)
    payment_date:date
    material_code:str=Field(pattern=r"^[A-Z0-9_-]{1,40}$")
    evidence_ref:str=Field(min_length=1,max_length=160)
class PricingIn(StrictInput):
    purchase_order_id:StrictInt=Field(gt=0)
    change_percent:Decimal=Field(ge=-100,le=100)
    evidence_ref:str=Field(min_length=1,max_length=160)
class RFQIn(StrictInput):
    counterparty_id:StrictInt=Field(gt=0)
    material_code:str=Field(pattern=r"^[A-Z0-9_-]{1,40}$")
    quantity:StrictInt=Field(gt=0,le=1000000)
    needed_date:date
    evidence_ref:str=Field(min_length=1,max_length=160)
def party(db,seller_id,party_id):
    row=db.scalar(select(KoshCounterparty).where(KoshCounterparty.id==party_id,KoshCounterparty.seller_id==seller_id))
    if row is None:raise HTTPException(404,"Counterparty not found")
    return row
def owned(db,seller_id,record_id,kind=None):
    row=db.scalar(select(KoshOperationRecord).where(KoshOperationRecord.id==record_id,KoshOperationRecord.seller_id==seller_id).with_for_update())
    if row is None or (kind and row.kind!=kind):raise HTTPException(404,"Operation record not found")
    return row
def record(db,seller_id,access,action,payload,tier="T1"):
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action=action,tier=tier,payload=payload,policy_decision="ALLOW");db.commit()
@router.get("")
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    items=[out(row) for row in db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id).order_by(KoshOperationRecord.id.desc()))]
    record(db,seller_id,access,"operations.read",{},"T0");return {"items":items,"role":access.role,"counterparties":[{"id":p.id,"name":p.name,"kind":p.kind} for p in db.scalars(select(KoshCounterparty).where(KoshCounterparty.seller_id==seller_id))],"market_sample":MARKET_SAMPLE,"external_delivery":False}
@router.post("/orders")
def order(seller_id:int,payload:OrderIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);party(db,seller_id,payload.counterparty_id)
    event=KoshCashEvent(seller_id=seller_id,event_type="EXPECTED_RECEIVABLE" if payload.direction=="SALE" else "SCHEDULED_PAYABLE",source_module="sales" if payload.direction=="SALE" else "procurement",evidence_ref=payload.evidence_ref,event_date=payload.payment_date,amount_paise=payload.amount_paise,status="PROPOSED",created_by_user_id=access.user_id);db.add(event);db.flush()
    data=payload.model_dump(mode="json");data["cash_event_id"]=event.id
    row=KoshOperationRecord(seller_id=seller_id,kind=payload.direction,evidence_ref=payload.evidence_ref,data=data,status="PROPOSED",created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,"operations.order.propose",{"record_id":row.id,"cash_event_id":event.id});return out(row)
@router.post("/orders/{record_id}/confirm")
def confirm_order(seller_id:int,record_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);row=owned(db,seller_id,record_id)
    if row.kind not in {"SALE","PO","PRICE_CHANGE"}:raise HTTPException(409,"This record has no cash-event confirmation")
    event=db.scalar(select(KoshCashEvent).where(KoshCashEvent.id==row.data['cash_event_id'],KoshCashEvent.seller_id==seller_id).with_for_update())
    if event is None:raise HTTPException(409,"Cash-event evidence missing")
    event.status="CONFIRMED";event.confirmed_at=event.confirmed_at or utcnow();event.confirmed_by_user_id=access.user_id;row.status="CONFIRMED";row.updated_at=utcnow();record(db,seller_id,access,"operations.order.confirm",{"record_id":row.id,"cash_event_id":event.id});return out(row)
@router.post("/pricing")
def pricing(seller_id:int,payload:PricingIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);po=owned(db,seller_id,payload.purchase_order_id,"PO")
    if po.status!="CONFIRMED":raise HTTPException(409,"Confirm the planned purchase first")
    delta=int((Decimal(po.data['amount_paise'])*payload.change_percent/100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    event=KoshCashEvent(seller_id=seller_id,event_type="COST_CHANGE",cost_direction="INCREASE" if delta>=0 else "DECREASE",source_module="pricing",evidence_ref=payload.evidence_ref,event_date=date.fromisoformat(po.data['payment_date']),amount_paise=abs(delta),status="PROPOSED",created_by_user_id=access.user_id);db.add(event);db.flush()
    row=KoshOperationRecord(seller_id=seller_id,kind="PRICE_CHANGE",evidence_ref=payload.evidence_ref,data={"purchase_order_id":po.id,"change_percent":str(payload.change_percent),"delta_paise":delta,"cash_event_id":event.id,"material_code":po.data['material_code']},status="PROPOSED",created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,"operations.pricing.propose",{"record_id":row.id,"delta_paise":delta});return out(row)
@router.post("/rfqs")
def rfq(seller_id:int,payload:RFQIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);recipient=party(db,seller_id,payload.counterparty_id)
    row=KoshAddonDraft(seller_id=seller_id,module="procurement",kind="RFQ_MESSAGE",body=f"Request quotation for {payload.quantity} units of {payload.material_code}, required {payload.needed_date.isoformat()}. Please provide price and delivery terms.",params={"counterparty_id":recipient.id,"amount_paise":0,"allowlist_key":f"counterparty:{recipient.id}","funding_date":payload.needed_date.isoformat(),"days":0,"cost_paise":0,"evidence_reference":payload.evidence_ref},evidence_hash="",status="DRAFT",created_by_user_id=access.user_id);row.evidence_hash=draft_hash(row);db.add(row);db.flush();record(db,seller_id,access,"operations.rfq.draft",{"draft_id":row.id});return {"id":row.id,"body":row.body,"tier":"T1","external_delivery":False}
@router.post("/drafts/{draft_id}/intent")
def intent(seller_id:int,draft_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=create_from_draft(db,seller_id=seller_id,draft_id=draft_id,creator_id=access.user_id)
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))
    db.commit();return out(row)
