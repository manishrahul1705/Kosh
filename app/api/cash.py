"""Seller-scoped ledger, obligations and audit reads/writes."""
from datetime import date
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit,require_seller_read
from app.audit.ledger import append_event
from app.audit.verify import verify_chain
from app.database.kosh_models import KoshAuditEntry,KoshBankTransaction,KoshCounterparty,KoshInvoice,KoshObligation
from app.schemas.kosh import ForecastResponse,AlertsResponse,PlanResponse,ApprovalsResponse

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

@router.get("/forecast/latest",response_model=ForecastResponse)
def forecast(seller_id:int,access:AuthorizedSeller=Depends(require_seller_read)):return ForecastResponse(seller_id=seller_id)
@router.get("/alerts",response_model=AlertsResponse)
def alerts(seller_id:int,access:AuthorizedSeller=Depends(require_seller_read)):return AlertsResponse(seller_id=seller_id)
@router.get("/plan",response_model=PlanResponse)
def plan(seller_id:int,access:AuthorizedSeller=Depends(require_seller_read)):return PlanResponse(seller_id=seller_id)
@router.get("/approvals",response_model=ApprovalsResponse)
def approvals(seller_id:int,access:AuthorizedSeller=Depends(require_seller_read)):return ApprovalsResponse(seller_id=seller_id)
