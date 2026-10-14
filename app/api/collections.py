"""Evidence-backed collections with approval-gated sandbox outreach."""
from datetime import date
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictInt,StrictBool,Field,model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_edit,require_seller_owner
from app.database.kosh_models import KoshInvoice,KoshCounterparty,KoshCollectionTerms,KoshAddonDraft
from app.database.session import reserve_sqlite_writer
from app.finance.collections import msmed_interest,reminder
from app.core.config import get_settings
from app.audit.ledger import append_event
from app.actions.addons import draft_hash,create_from_draft
from app.actions.read import out
from app.policy.internal import gate
from app.policy.rules import evaluate
from app.policy.controls import context
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/collections",tags=["kosh-collections"])
def record(db,seller_id,access,action,payload,tier="T1"):
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action=action,tier=tier,payload=payload,policy_decision="ALLOW");db.commit()
def owned_invoice(db,seller_id,invoice_id):
    row=db.scalar(select(KoshInvoice).where(KoshInvoice.id==invoice_id,KoshInvoice.seller_id==seller_id,KoshInvoice.direction=="RECEIVABLE",KoshInvoice.status=="OPEN"))
    if row is None:raise HTTPException(404,"Open receivable not found")
    return row
class TermsIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    acceptance_date:date
    agreement_status:Literal["NONE","AGREED"]
    agreed_days:StrictInt|None=Field(default=None,ge=0,le=365)
    supplier_mse:StrictBool
    evidence_ref:str=Field(min_length=1,max_length=160)
    @model_validator(mode="after")
    def consistent(self):
        if (self.agreement_status=="AGREED")!=(self.agreed_days is not None):raise ValueError("Agreed days required only for a documented agreement")
        return self
class DraftIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    invoice_id:StrictInt
    tone:Literal["GENTLE","PROFESSIONAL","FIRM"]="PROFESSIONAL"
@router.get("")
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    as_of=date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat());items=[]
    for invoice,party in db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id,KoshInvoice.direction=="RECEIVABLE",KoshInvoice.status=="OPEN",KoshInvoice.due_date<as_of)):
        terms=db.get(KoshCollectionTerms,invoice.id)
        interest=msmed_interest(max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0)),terms.acceptance_date if terms else None,as_of,agreement_status=terms.agreement_status if terms else "UNKNOWN",agreed_days=terms.agreed_days if terms else None,supplier_mse=terms.supplier_mse if terms else None)
        items.append({"invoice_id":invoice.id,"invoice_number":invoice.invoice_number,"party":party.name,"amount_paise":max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0)),"interest":interest,"evidence_ref":terms.evidence_ref if terms else None})
    record(db,seller_id,access,"collections.read",{},"T0");return {"items":items,"role":access.role}
@router.put("/{invoice_id}/terms")
def terms(seller_id:int,invoice_id:int,payload:TermsIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);invoice=owned_invoice(db,seller_id,invoice_id)
    if payload.acceptance_date<invoice.invoice_date:raise HTTPException(422,"Acceptance cannot precede issue date")
    row=db.get(KoshCollectionTerms,invoice.id)
    if row is None:row=KoshCollectionTerms(invoice_id=invoice.id,seller_id=seller_id);db.add(row)
    for key,value in payload.model_dump().items():setattr(row,key,value)
    record(db,seller_id,access,"collections.terms",{"invoice_id":invoice.id,"evidence_ref":payload.evidence_ref});return {"status":"DOCUMENTED"}
@router.post("/drafts")
def draft(seller_id:int,payload:DraftIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True)
    decision=evaluate("REMINDER_DRAFT",{},context(db,seller_id),origin="ADDON:collections")
    if decision.decision=="DENY":
        append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="security.intent_blocked",tier="T4",payload={"policy":decision.as_dict()},policy_decision="DENY");db.commit();raise HTTPException(403,decision.as_dict())
    invoice=owned_invoice(db,seller_id,payload.invoice_id);party=db.get(KoshCounterparty,invoice.counterparty_id)
    params={"amount_paise":max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0)),"invoice_id":invoice.id,"counterparty_id":party.id,"allowlist_key":f"counterparty:{party.id}","funding_date":date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat()).isoformat(),"days":0,"cost_paise":0}
    row=KoshAddonDraft(seller_id=seller_id,module="collections",kind="COLLECTIONS_REMINDER",params=params,body=reminder(invoice,party,tone=payload.tone),evidence_hash="",status="DRAFT",created_by_user_id=access.user_id);row.evidence_hash=draft_hash(row);db.add(row);db.flush();record(db,seller_id,access,"collections.draft",{"draft_id":row.id,"invoice_id":invoice.id});return {"id":row.id,"body":row.body,"tier":"T1","params":row.params}
@router.post("/drafts/{draft_id}/intent")
def send_intent(seller_id:int,draft_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=create_from_draft(db,seller_id=seller_id,draft_id=draft_id,creator_id=access.user_id)
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))
    db.commit();return out(row)
