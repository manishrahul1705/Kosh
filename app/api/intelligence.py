"""Customer evidence and same-seed cash scenarios; scenarios never create actions."""
from datetime import date
from decimal import Decimal,ROUND_HALF_UP
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictInt,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_edit,require_seller_owner
from app.database.kosh_models import KoshCounterparty,KoshOperationRecord,KoshForecastRun
from app.database.session import reserve_sqlite_writer
from app.finance.intelligence import customer_snapshot
from app.finance.forecast import load_inputs,simulate
from app.core.config import get_settings
from app.audit.ledger import append_event
from app.policy.internal import gate
from app.utils.dates import utcnow
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/intelligence",tags=["kosh-intelligence"])
class StrictInput(BaseModel):model_config=ConfigDict(extra="forbid")
class HistoryIn(StrictInput):
    counterparty_id:StrictInt=Field(gt=0)
    observed_date:date
    delay_days:list[StrictInt]=Field(min_length=1,max_length=100)
    evidence_ref:str=Field(min_length=1,max_length=160)
class ScenarioIn(StrictInput):
    counterparty_id:StrictInt|None=None
    delay_shift_days:StrictInt=Field(default=0,ge=-60,le=120)
    purchase_order_id:StrictInt|None=None
    price_change_percent:Decimal=Field(default=Decimal(0),ge=-100,le=100)
def record(db,seller_id,access,action,payload,tier="T0"):
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action=action,tier=tier,payload=payload,policy_decision="ALLOW");db.commit()
@router.get("")
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    as_of=date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat());items=customer_snapshot(db,seller_id,as_of)
    history=[{"id":r.id,"status":r.status,"data":r.data,"evidence_ref":r.evidence_ref} for r in db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=="PAYMENT_HISTORY"))]
    record(db,seller_id,access,"intelligence.read",{});return {"items":items,"history":history,"role":access.role,"history_label":"Optional owner-confirmed additional payment observations; switchable"}
@router.post("/history")
def propose_history(seller_id:int,payload:HistoryIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id)
    if any(day<0 or day>730 for day in payload.delay_days):raise HTTPException(422,"Delay observations must be between zero and 730 days")
    if db.scalar(select(KoshCounterparty.id).where(KoshCounterparty.id==payload.counterparty_id,KoshCounterparty.seller_id==seller_id)) is None:raise HTTPException(404,"Customer not found")
    row=KoshOperationRecord(seller_id=seller_id,kind="PAYMENT_HISTORY",evidence_ref=payload.evidence_ref,data=payload.model_dump(mode="json"),status="PROPOSED",created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,"intelligence.history.propose",{"id":row.id},"T1");return {"id":row.id,"status":row.status}
@router.post("/history/{record_id}/confirm")
def confirm_history(seller_id:int,record_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id)
    row=db.scalar(select(KoshOperationRecord).where(KoshOperationRecord.id==record_id,KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=="PAYMENT_HISTORY").with_for_update())
    if row is None:raise HTTPException(404,"History evidence not found")
    row.status="CONFIRMED";row.updated_at=utcnow();record(db,seller_id,access,"intelligence.history.confirm",{"id":row.id},"T1");return {"id":row.id,"status":row.status}
@router.post("/whatif")
def whatif(seller_id:int,payload:ScenarioIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()))
    if run is None:raise HTTPException(409,"Run a base forecast first")
    shifts={};extras=[]
    if payload.counterparty_id is not None:
        if db.scalar(select(KoshCounterparty.id).where(KoshCounterparty.id==payload.counterparty_id,KoshCounterparty.seller_id==seller_id)) is None:raise HTTPException(404,"Customer not found")
        shifts[payload.counterparty_id]=payload.delay_shift_days
    elif payload.delay_shift_days:raise HTTPException(422,"Specify the customer for a delay scenario")
    if payload.purchase_order_id is not None:
        po=db.scalar(select(KoshOperationRecord).where(KoshOperationRecord.id==payload.purchase_order_id,KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=="PO",KoshOperationRecord.status=="CONFIRMED"))
        if po is None:raise HTTPException(404,"Confirmed purchase not found")
        delta=int((Decimal(po.data['amount_paise'])*payload.price_change_percent/100).quantize(Decimal(1),rounding=ROUND_HALF_UP));extras.append({"date":po.data['payment_date'],"amount_paise":-delta})
    elif payload.price_change_percent:raise HTTPException(422,"Specify the confirmed purchase exposure")
    inputs=load_inputs(db,seller_id,run.as_of_date,include_addon_events=run.params.get('include_addon_events',True),include_customer_history=run.params.get('include_customer_history',False))
    result=simulate(inputs,as_of=run.as_of_date,n_paths=run.n_paths,seed=run.seed,include_forecast_sales=run.include_forecast_sales,buffer_paise=run.buffer_paise,customer_delay_shift_days=shifts,extra_inflows=extras)
    record(db,seller_id,access,"intelligence.whatif",{"base_run_id":run.id,"scenario":payload.model_dump(mode="json")});return {"base_run_id":run.id,"scenario_only":True,"assumptions":"Owned customer delay shift; percentage applied only to the chosen confirmed PO.",**result}
