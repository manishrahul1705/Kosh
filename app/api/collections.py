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
    acceptance_date:date|None=None
    agreement_status:Literal["UNKNOWN","NONE","AGREED"]="UNKNOWN"
    agreed_days:StrictInt|None=Field(default=None,ge=0,le=45)
    supplier_mse:StrictBool|Literal["UNKNOWN","APPLICABLE","NOT_APPLICABLE"]|None=None
    evidence_ref:str|None=Field(default=None,max_length=160)
    @model_validator(mode="after")
    def consistent(self):
        if isinstance(self.supplier_mse,str):
            if self.supplier_mse=="APPLICABLE":self.supplier_mse=True
            elif self.supplier_mse=="NOT_APPLICABLE":self.supplier_mse=False
            else:self.supplier_mse=None
        if self.agreement_status=="AGREED":
            if self.agreed_days is None:raise ValueError("Agreed days required for documented agreed period")
            if self.agreed_days<0 or self.agreed_days>45:raise ValueError("Agreed payment period cannot exceed 45 days under Section 15 of MSMED Act")
        else:
            if self.agreed_days is not None:raise ValueError("Agreed days must not be set when agreement status is not AGREED")
        return self
class DraftIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    invoice_id:StrictInt
    channel:Literal["EMAIL","WHATSAPP"]="EMAIL"
    tone:Literal["GENTLE","PROFESSIONAL","FIRM"]="PROFESSIONAL"
@router.get("")
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    as_of=date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat());items=[];open_invoices=[]
    all_open=db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id,KoshInvoice.direction=="RECEIVABLE",KoshInvoice.status=="OPEN").order_by(KoshInvoice.due_date,KoshInvoice.id)).all()
    for invoice,party in all_open:
        terms_row=db.get(KoshCollectionTerms,invoice.id)
        principal=max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0))
        interest=msmed_interest(principal,terms_row.acceptance_date if terms_row else None,as_of,agreement_status=terms_row.agreement_status if terms_row else "UNKNOWN",agreed_days=terms_row.agreed_days if terms_row else None,supplier_mse=terms_row.supplier_mse if terms_row else None)
        terms_data={"acceptance_date":terms_row.acceptance_date.isoformat() if terms_row and terms_row.acceptance_date else None,"agreement_status":terms_row.agreement_status if terms_row else "UNKNOWN","agreed_days":terms_row.agreed_days if terms_row else None,"supplier_mse":terms_row.supplier_mse if terms_row else None,"evidence_ref":terms_row.evidence_ref if terms_row else None} if terms_row else None
        invoice_dict={"invoice_id":invoice.id,"invoice_number":invoice.invoice_number,"party":party.name,"amount_paise":principal,"invoice_date":invoice.invoice_date.isoformat(),"due_date":invoice.due_date.isoformat(),"is_overdue":invoice.due_date<as_of,"interest":interest,"total_paise":principal+(interest.get("interest_paise") or 0),"evidence_ref":terms_row.evidence_ref if terms_row else None,"terms":terms_data}
        open_invoices.append(invoice_dict)
        if invoice.due_date<as_of:items.append(invoice_dict)
    demo_calc=msmed_interest(10000000,date(2026,1,1),date(2026,3,16),agreement_status="NONE",supplier_mse=True)
    demo_fixture={"label":"Fictional Overdue Statutory Interest Demonstration Fixture","note":"Separately labelled fictional fixture. Seeded ABC invoices are not overdue on 2026-10-13. Does not affect actual cash or ledger.","invoice_number":"FICT-DEMO-001","party":"Fictional Buyer Ltd","principal_paise":10000000,"acceptance_date":"2026-01-01","agreement_status":"NONE","agreed_days":None,"supplier_mse":True,"evidence_ref":"fictional-demo:contract-clause-12","due_date":demo_calc.get("due_date","2026-01-16"),"as_of":"2026-03-16","overdue_days":demo_calc.get("overdue_days",59),"interest":demo_calc,"total_paise":10000000+(demo_calc.get("interest_paise") or 0)}
    record(db,seller_id,access,"collections.read",{},"T0");return {"items":items,"open_invoices":open_invoices,"role":access.role,"as_of":as_of.isoformat(),"fixture":demo_fixture}
@router.get("/{invoice_id}/terms")
def get_terms(seller_id:int,invoice_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    invoice=owned_invoice(db,seller_id,invoice_id)
    as_of=date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat())
    terms_row=db.get(KoshCollectionTerms,invoice.id)
    principal=max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0))
    interest=msmed_interest(principal,terms_row.acceptance_date if terms_row else None,as_of,agreement_status=terms_row.agreement_status if terms_row else "UNKNOWN",agreed_days=terms_row.agreed_days if terms_row else None,supplier_mse=terms_row.supplier_mse if terms_row else None)
    return {"invoice_id":invoice.id,"invoice_number":invoice.invoice_number,"invoice_date":invoice.invoice_date.isoformat(),"due_date":invoice.due_date.isoformat(),"is_overdue":invoice.due_date<as_of,"as_of":as_of.isoformat(),"principal_paise":principal,"interest":interest,"total_paise":principal+(interest.get("interest_paise") or 0),"terms":{"acceptance_date":terms_row.acceptance_date.isoformat() if terms_row and terms_row.acceptance_date else None,"agreement_status":terms_row.agreement_status if terms_row else "UNKNOWN","agreed_days":terms_row.agreed_days if terms_row else None,"supplier_mse":terms_row.supplier_mse if terms_row else None,"evidence_ref":terms_row.evidence_ref if terms_row else None} if terms_row else None}
@router.put("/{invoice_id}/terms")
def terms(seller_id:int,invoice_id:int,payload:TermsIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);invoice=owned_invoice(db,seller_id,invoice_id)
    as_of=date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat())
    if payload.acceptance_date is not None:
        if payload.acceptance_date>as_of:raise HTTPException(422,f"Acceptance date cannot be in the future (after calculation as-of date {as_of.isoformat()})")
        if payload.acceptance_date<invoice.invoice_date:raise HTTPException(422,"Acceptance cannot precede issue date")
    row=db.get(KoshCollectionTerms,invoice.id)
    if row is None:row=KoshCollectionTerms(invoice_id=invoice.id,seller_id=seller_id);db.add(row)
    row.acceptance_date=payload.acceptance_date
    row.agreement_status=payload.agreement_status
    row.agreed_days=payload.agreed_days if payload.agreement_status=="AGREED" else None
    row.supplier_mse=payload.supplier_mse
    row.evidence_ref=(payload.evidence_ref or "").strip()
    from app.database.kosh_models import KoshPlan,KoshPlanLine
    affected_lines=db.scalars(select(KoshPlanLine).join(KoshPlan,KoshPlan.id==KoshPlanLine.plan_id).where(KoshPlan.seller_id==seller_id,KoshPlan.status=="VALID")).all()
    for l in affected_lines:
        if invoice.id in (l.scope_ids or []):
            plan=db.get(KoshPlan,l.plan_id)
            if plan and plan.status=="VALID":
                plan.status="STALE";details=dict(plan.planning_details);details["why_this_plan"]="Invoice terms or evidence changed. Re-evaluate financing and build a current plan.";plan.planning_details=details
    principal=max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0))
    interest=msmed_interest(principal,row.acceptance_date,as_of,agreement_status=row.agreement_status,agreed_days=row.agreed_days,supplier_mse=row.supplier_mse)
    record(db,seller_id,access,"collections.terms",{"invoice_id":invoice.id,"acceptance_date":row.acceptance_date.isoformat() if row.acceptance_date else None,"agreement_status":row.agreement_status,"agreed_days":row.agreed_days,"supplier_mse":row.supplier_mse,"evidence_ref":row.evidence_ref,"interest_status":interest["status"],"interest_paise":interest["interest_paise"]})
    return {"status":"DOCUMENTED","invoice_id":invoice.id,"principal_paise":principal,"interest":interest,"total_paise":principal+(interest.get("interest_paise") or 0),"as_of":as_of.isoformat()}
@router.post("/drafts")
def draft(seller_id:int,payload:DraftIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True)
    decision=evaluate("REMINDER_DRAFT",{},context(db,seller_id),origin="ADDON:collections")
    if decision.decision=="DENY":
        append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="security.intent_blocked",tier="T4",payload={"policy":decision.as_dict()},policy_decision="DENY");db.commit();raise HTTPException(403,decision.as_dict())
    gate(db,seller_id,access.user_id,source="ADDON:collections")
    invoice=owned_invoice(db,seller_id,payload.invoice_id);party=db.get(KoshCounterparty,invoice.counterparty_id)
    params={"feature_module":"collections","channel":payload.channel,"amount_paise":max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0)),"invoice_id":invoice.id,"counterparty_id":party.id,"allowlist_key":f"counterparty:{party.id}","funding_date":date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat()).isoformat(),"days":0,"cost_paise":0}
    row=KoshAddonDraft(seller_id=seller_id,module="collections",kind="COLLECTIONS_REMINDER",params=params,body=reminder(invoice,party,tone=payload.tone),evidence_hash="",status="DRAFT",created_by_user_id=access.user_id);row.evidence_hash=draft_hash(row);db.add(row);db.flush();record(db,seller_id,access,"collections.draft",{"draft_id":row.id,"invoice_id":invoice.id});return {"id":row.id,"body":row.body,"tier":"T1","params":row.params}
@router.post("/drafts/{draft_id}/intent")
def send_intent(seller_id:int,draft_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=create_from_draft(db,seller_id=seller_id,draft_id=draft_id,creator_id=access.user_id)
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))
    db.commit();return out(row)
