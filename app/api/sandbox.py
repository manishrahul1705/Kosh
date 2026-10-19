"""Authorized local sandbox inbox; no external delivery capability."""
from datetime import date
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_approval,require_seller_read,require_seller_owner
from app.actions.step_up import inbox
from app.audit.ledger import append_event
from app.core.config import get_settings
from app.database.kosh_models import KoshSandboxExecution,KoshSandboxLedgerEntry,KoshSandboxOutbox
from app.policy.controls import editable_control
from app.sandbox.adapters import balance,reconcile

def record_read(db,seller_id,access,action,payload=None):
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action=action,tier="T0",payload=payload or {},policy_decision="ALLOW");db.commit()

def row_out(row):
    return {c.name:getattr(row,c.name) for c in row.__table__.columns}

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/sandbox",tags=["kosh-sandbox"])

@router.get("/inbox")
def read_inbox(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    if get_settings().app_env.strip().lower()=="production":raise HTTPException(403,"Sandbox OTP inbox is disabled in production")
    items=inbox(db,seller_id=seller_id,actor_id=access.user_id)
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="sandbox.inbox.read",tier="T0",payload={"count":len(items)},policy_decision="ALLOW");db.commit()
    return {"seller_id":seller_id,"items":items}

@router.get("/executions")
def executions(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.scalars(select(KoshSandboxExecution).where(KoshSandboxExecution.seller_id==seller_id).order_by(KoshSandboxExecution.created_at.desc())).all()
    record_read(db,seller_id,access,"sandbox.executions.read")
    return {"seller_id":seller_id,"items":[row_out(row) for row in rows]}

@router.get("/outbox")
def outbox(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.scalars(select(KoshSandboxOutbox).where(KoshSandboxOutbox.seller_id==seller_id).order_by(KoshSandboxOutbox.created_at.desc())).all()
    record_read(db,seller_id,access,"sandbox.outbox.read")
    return {"seller_id":seller_id,"items":[row_out(row) for row in rows],"external_delivery":False}

@router.get("/statement")
def statement(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.scalars(select(KoshSandboxLedgerEntry).where(KoshSandboxLedgerEntry.seller_id==seller_id).order_by(KoshSandboxLedgerEntry.entry_date,KoshSandboxLedgerEntry.id)).all()
    record_read(db,seller_id,access,"sandbox.statement.read")
    return {"seller_id":seller_id,"source":"SANDBOX","items":[row_out(row) for row in rows]}

@router.get("/balance")
def read_balance(seller_id:int,as_of:date|None=None,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    as_of=as_of or date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat())
    result=balance(db,seller_id,as_of=as_of);record_read(db,seller_id,access,"sandbox.balance.read",{"as_of":as_of})
    return {"seller_id":seller_id,**result}

@router.get("/reconciliation")
def reconciliation(seller_id:int,execution_id:str|None=None,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    if execution_id and db.scalar(select(KoshSandboxExecution.id).where(KoshSandboxExecution.id==execution_id,KoshSandboxExecution.seller_id==seller_id)) is None:raise HTTPException(404,"Execution not found")
    result=reconcile(db,seller_id,execution_id);record_read(db,seller_id,access,"sandbox.reconcile",result)
    return {"seller_id":seller_id,**result}

class FailureIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    enabled:StrictBool

@router.post("/failure-injection")
def failure_injection(seller_id:int,payload:FailureIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    if get_settings().app_env.strip().lower()=="production":raise HTTPException(403,"Failure injection is development-only")
    row=editable_control(db,seller_id);row.sandbox_fail_next=payload.enabled
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="sandbox.failure_injection",tier="T1",payload={"enabled":payload.enabled},policy_decision="ALLOW");db.commit()
    return {"fail_next":row.sandbox_fail_next}
