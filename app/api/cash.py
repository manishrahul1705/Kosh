"""Seller-scoped ledger, obligations and audit reads/writes."""
from datetime import date
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit,require_seller_read
from app.audit.ledger import append_event
from app.audit.verify import verify_chain
from app.database.kosh_models import KoshAlert,KoshAuditEntry,KoshBacktest,KoshBankTransaction,KoshCounterparty,KoshForecastRun,KoshForecastWeek,KoshInvoice,KoshObligation
from app.core.config import get_settings
from app.finance.forecast import buffer_for_seller,fingerprint,load_inputs,simulate
from app.finance.alerts import build_alert
from app.finance.analysis import business_analysis
from app.finance.backtest import run_backtest
from app.utils.dates import utcnow
from app.schemas.kosh import ForecastResponse,AlertsResponse,ApprovalsResponse

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}",tags=["kosh"])

def invoice_out(i,party):return {"id":i.id,"direction":i.direction,"party":party.name,"invoice_number":i.invoice_number,"invoice_date":i.invoice_date,"due_date":i.due_date,"amount_paise":i.amount_paise,"status":i.status,"paid_date":i.paid_date,"paid_amount_paise":i.paid_amount_paise,"source_document_version_id":i.source_document_version_id,"source_location":i.source_location}

@router.get("/ledger")
def get_ledger(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id).order_by(KoshInvoice.due_date)).all()
    invoices=[invoice_out(i,p) for i,p in rows];today=date.today()
    def remaining(i):return max(0,i.amount_paise-(i.paid_amount_paise or 0))
    open_receivables=sum(remaining(i) for i,_ in rows if i.direction=="RECEIVABLE" and i.status!="PAID")
    open_payables=sum(remaining(i) for i,_ in rows if i.direction=="PAYABLE" and i.status!="PAID")
    overdue=sum(remaining(i) for i,_ in rows if i.direction=="RECEIVABLE" and i.status!="PAID" and i.due_date<today)
    latest=db.scalar(select(KoshBankTransaction).where(KoshBankTransaction.seller_id==seller_id).order_by(KoshBankTransaction.txn_date.desc(),KoshBankTransaction.id.desc()).limit(1))
    return {"seller_id":seller_id,"totals":{"open_receivables_paise":open_receivables,"open_payables_paise":open_payables,"overdue_receivables_paise":overdue,"review_count":sum(i.status=="REVIEW" for i,_ in rows),"latest_bank_balance_paise":latest.balance_paise if latest else None,"bank_balance_as_of":latest.txn_date if latest else None},"items":invoices}

class InvoicePatch(BaseModel):
    amount_paise:int|None=None;invoice_date:date|None=None;due_date:date|None=None;invoice_number:str|None=None

@router.patch("/invoices/{invoice_id}")
def patch_invoice(seller_id:int,invoice_id:int,payload:InvoicePatch,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    row=db.scalar(select(KoshInvoice).where(KoshInvoice.id==invoice_id,KoshInvoice.seller_id==seller_id))
    if not row:raise HTTPException(404,"Invoice not found")
    before={k:getattr(row,k) for k in payload.model_fields_set}|{"status":row.status}
    for key,value in payload.model_dump(exclude_unset=True).items():setattr(row,key,value)
    row.status="OPEN";after={k:getattr(row,k) for k in payload.model_fields_set}|{"status":row.status}
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="ledger.correct",tier="T1_DRAFT",payload={"invoice_id":row.id,"before":before,"after":after},policy_decision="ALLOW");db.commit();return {"id":row.id,"status":row.status}

class ObligationIn(BaseModel):
    kind:str;label:str;amount_paise:int;recurrence:str;next_due_date:date;day_of_month:int|None=None;active:bool=True

@router.get("/obligations")
def obligations(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    return [{c.name:getattr(x,c.name) for c in x.__table__.columns} for x in db.scalars(select(KoshObligation).where(KoshObligation.seller_id==seller_id))]

@router.post("/obligations")
def add_obligation(seller_id:int,payload:ObligationIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    row=KoshObligation(seller_id=seller_id,**payload.model_dump());db.add(row);append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="obligation.create",tier="T1_DRAFT",payload=payload.model_dump(),policy_decision="ALLOW");db.commit();return {"id":row.id}

@router.patch("/obligations/{obligation_id}")
def update_obligation(seller_id:int,obligation_id:int,payload:ObligationIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    row=db.scalar(select(KoshObligation).where(KoshObligation.id==obligation_id,KoshObligation.seller_id==seller_id))
    if not row:raise HTTPException(404,"Obligation not found")
    for key,value in payload.model_dump().items():setattr(row,key,value)
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="obligation.update",tier="T1_DRAFT",payload={"obligation_id":row.id,**payload.model_dump()},policy_decision="ALLOW");db.commit();return {"id":row.id}

@router.get("/audit")
def get_audit(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.scalars(select(KoshAuditEntry).where(KoshAuditEntry.seller_id==seller_id).order_by(KoshAuditEntry.sequence.desc()).limit(100)).all();return {"seller_id":seller_id,"status":"READY","items":[{"sequence":x.sequence,"recorded_at":x.recorded_at,"actor_type":x.actor_type,"action":x.action,"tier":x.tier,"policy_decision":x.policy_decision} for x in rows]}

@router.get("/audit/verify")
def verify_audit(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    result=verify_chain(db);return result.__dict__

def _as_of()->date:
    value=get_settings().kosh_as_of_date
    return date.fromisoformat(value) if value else date.today()

def _week_out(row):return {column.name:getattr(row,column.name) for column in row.__table__.columns if column.name!="id"}
def _alert_out(row):return None if not row else {column.name:getattr(row,column.name) for column in row.__table__.columns}
def _latest(db,seller_id):return db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.created_at.desc(),KoshForecastRun.id.desc()).limit(1))
def _forecast_out(db,run):
    weeks=db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id).order_by(KoshForecastWeek.week_index)).all();alert=db.scalar(select(KoshAlert).where(KoshAlert.run_id==run.id).order_by(KoshAlert.id.desc()).limit(1))
    review=db.scalar(select(func.coalesce(func.sum(KoshInvoice.amount_paise-func.coalesce(KoshInvoice.paid_amount_paise,0)),0)).where(KoshInvoice.seller_id==run.seller_id,KoshInvoice.status=="REVIEW"))
    return {"seller_id":run.seller_id,"run":{"id":run.id,"as_of_date":run.as_of_date,"horizon_weeks":run.horizon_weeks,"n_paths":run.n_paths,"seed":run.seed,"input_fingerprint":run.input_fingerprint,"include_forecast_sales":run.include_forecast_sales,"buffer_paise":run.buffer_paise,"status":run.status,"created_at":run.created_at},"weeks":[_week_out(row) for row in weeks],"under_review_paise":review,"alert":_alert_out(alert)}

class ForecastRunIn(BaseModel):
    include_forecast_sales:bool=True;n_paths:int=Field(default=2000,ge=1,le=10000);seed:int=42
class WhatIfIn(BaseModel):
    customer_delay_shift_days:dict[int,int]={};exclude_counterparties:list[int]=[];extra_inflows:list[dict]=[]

@router.post("/forecast/run")
def run_forecast(seller_id:int,payload:ForecastRunIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    as_of=_as_of();inputs=load_inputs(db,seller_id,as_of);buffer=buffer_for_seller(db,seller_id);params=payload.model_dump();digest=fingerprint(inputs,{**params,"as_of_date":as_of,"buffer_paise":buffer})
    result=simulate(inputs,as_of=as_of,n_paths=payload.n_paths,seed=payload.seed,include_forecast_sales=payload.include_forecast_sales,buffer_paise=buffer)
    run=KoshForecastRun(seller_id=seller_id,as_of_date=as_of,horizon_weeks=13,n_paths=payload.n_paths,seed=payload.seed,params=params,input_fingerprint=digest,include_forecast_sales=payload.include_forecast_sales,buffer_paise=buffer,status="SUCCESS",created_by_user_id=access.user_id);db.add(run);db.flush()
    for week in result["weeks"]:db.add(KoshForecastWeek(run_id=run.id,**week))
    for old in db.scalars(select(KoshAlert).where(KoshAlert.seller_id==seller_id,KoshAlert.status=="OPEN")):old.status="SUPERSEDED"
    proposed=build_alert(inputs,result,as_of=as_of,threshold=get_settings().kosh_alert_threshold)
    if proposed:db.add(KoshAlert(seller_id=seller_id,run_id=run.id,status="OPEN",**{key:proposed[key] for key in ("week_index","probability","expected_shortfall_paise","peak_expected_shortfall_paise","causes")}))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="forecast.run",tier="T0_READ",payload={"run_id":run.id,"input_fingerprint":digest},policy_decision="ALLOW");db.commit();return {"run_id":run.id}

@router.get("/forecast/latest")
def forecast(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    run=_latest(db,seller_id)
    if not run:return {"seller_id":seller_id,"status":"NOT_IMPLEMENTED","items":[]}
    return _forecast_out(db,run)

@router.post("/forecast/whatif")
def whatif(seller_id:int,payload:WhatIfIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    run=_latest(db,seller_id)
    if not run:raise HTTPException(404,"No forecast run")
    result=simulate(load_inputs(db,seller_id,run.as_of_date),as_of=run.as_of_date,n_paths=run.n_paths,seed=run.seed,include_forecast_sales=run.include_forecast_sales,buffer_paise=run.buffer_paise,customer_delay_shift_days=payload.customer_delay_shift_days,exclude_counterparties=set(payload.exclude_counterparties),extra_inflows=payload.extra_inflows)
    return {"seller_id":seller_id,"run":{"id":run.id,"as_of_date":run.as_of_date,"buffer_paise":run.buffer_paise},"weeks":result["weeks"],"under_review_paise":result["under_review_paise"],"alert":build_alert(load_inputs(db,seller_id,run.as_of_date),result,as_of=run.as_of_date,threshold=get_settings().kosh_alert_threshold)}

@router.get("/alerts")
def alerts(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.scalars(select(KoshAlert).where(KoshAlert.seller_id==seller_id).order_by(KoshAlert.created_at.desc())).all()
    return [_alert_out(row) for row in rows] if rows else {"seller_id":seller_id,"status":"NOT_IMPLEMENTED","items":[]}

@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(seller_id:int,alert_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    row=db.scalar(select(KoshAlert).where(KoshAlert.id==alert_id,KoshAlert.seller_id==seller_id))
    if not row:raise HTTPException(404,"Alert not found")
    row.status="ACKNOWLEDGED";row.acknowledged_by=access.user_id;row.acknowledged_at=utcnow();append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="alert.acknowledge",tier="T1_DRAFT",payload={"alert_id":alert_id},policy_decision="ALLOW");db.commit();return {"id":row.id,"status":row.status}

@router.post("/forecast/backtest")
def backtest(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    result=run_backtest(db,seller_id,_as_of());row=KoshBacktest(seller_id=seller_id,**result);db.add(row);append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="forecast.backtest",tier="T0_READ",payload={"as_of_date":result["as_of_date"]},policy_decision="ALLOW");db.commit();return {"id":row.id}

@router.get("/forecast/backtest/latest")
def latest_backtest(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=db.scalar(select(KoshBacktest).where(KoshBacktest.seller_id==seller_id).order_by(KoshBacktest.created_at.desc(),KoshBacktest.id.desc()).limit(1))
    if not row:raise HTTPException(404,"No backtest")
    return {column.name:getattr(row,column.name) for column in row.__table__.columns}

@router.get("/analysis")
def analysis(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):return business_analysis(db,seller_id,_as_of())
@router.get("/approvals",response_model=ApprovalsResponse)
def approvals(seller_id:int,access:AuthorizedSeller=Depends(require_seller_read)):return ApprovalsResponse(seller_id=seller_id)
