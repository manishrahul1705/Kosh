"""Seller-authorized financing evaluation and plan endpoints."""
from datetime import date
from decimal import Decimal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit,require_seller_read
from app.audit.ledger import append_event
from app.core.config import get_settings
from app.database.kosh_models import KoshFinancingEvaluation,KoshFinancingResult,KoshPlan,KoshPlanLine
from app.finance.plan import propose_plan
from app.finance.costs import financing_quote
from app.lending.catalogue import load_catalogue
from app.lending.service import run_evaluation

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}",tags=["kosh-financing"])
SORT_RULE="sorted by effective annual cost, lowest first; no provider pays for placement"
def _as_of():return date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat())
def _latest_eval(db,seller):return db.scalar(select(KoshFinancingEvaluation).where(KoshFinancingEvaluation.seller_id==seller).order_by(KoshFinancingEvaluation.id.desc()).limit(1))
def _result(row,products):
    product=products[row.product_id];return {"product_id":row.product_id,"display_name":product["display_name"],"provider_label":product["provider_label"],"scope":row.scope,"status":row.status,"max_amount_paise":row.max_amount_paise,"effective_annual_rate":row.effective_annual_rate,"arrival_business_days":row.arrival_business_days,"reasons":row.reasons,"evidence":row.evidence,"assumption":product["cost_model"].get("assumption",False),**financing_quote(product,row.max_amount_paise),"quote_basis":"90-day quote basis","cost_assumption":product["cost_model"].get("assumption_label","Illustrative catalogue terms"),"verify_before_relying":any(not c.get("source",{}).get("verified",False) for c in product["criteria"])}
@router.post("/financing/evaluate")
def evaluate(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=run_evaluation(db,seller_id,_as_of())
    except ValueError as exc:raise HTTPException(409,str(exc))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="financing.evaluate",tier="T1_DRAFT",payload={"evaluation_id":row.id},policy_decision="ALLOW");db.commit();return {"evaluation_id":row.id}
@router.get("/financing/options")
def options(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    ev=_latest_eval(db,seller_id);products={p["id"]:p for p in load_catalogue()};rows=[] if not ev else [_result(x,products) for x in db.scalars(select(KoshFinancingResult).where(KoshFinancingResult.evaluation_id==ev.id))]
    rows.sort(key=lambda x:(Decimal(x["effective_annual_rate"] or "999"),x["product_id"]));return {"seller_id":seller_id,"sort_rule":SORT_RULE,"items":rows}
@router.get("/financing/options/{product_id}/explain")
def explain(seller_id:int,product_id:str,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    data=options(seller_id,db,access);matches=[x for x in data["items"] if x["product_id"]==product_id]
    if not matches:raise HTTPException(404,"Product result not found")
    return {"product_id":product_id,"status":matches[0]["status"],"explanation":" ".join(r["reason"] for x in matches for r in x["reasons"])}
def _line_out(line):
    result={c.name:getattr(line,c.name) for c in line.__table__.columns}
    for evidence in line.evidence:
        for key in ("days","funding_date","repayment_date","repayment_assumption"):
            if key in evidence:result[key]=evidence[key]
    return result

def _plan_out(db,row):
    lines=db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id==row.id)).all();return {"id":row.id,"seller_id":row.seller_id,"forecast_run_id":row.forecast_run_id,"forecast_fingerprint":row.forecast_fingerprint,"method":row.method,"status":row.status,"total_cost_paise":row.total_cost_paise,"baseline_cost_paise":row.baseline_cost_paise,"before_probabilities":row.before_probabilities,"after_probabilities":row.after_probabilities,"planning_details":row.planning_details,"target_probability":row.planning_details.get("target_probability"),"why_this_plan":row.planning_details.get("why_this_plan") or next((e["why_this_plan"] for line in lines for e in line.evidence if "why_this_plan" in e),"No eligible capacity was selected."),"lines":[_line_out(x) for x in lines]}
class PlanIn(BaseModel):
    target_probability:Decimal|None=Field(default=None,ge=0,lt=1)
    loan_repayment_date:date|None=None

@router.get("/financing/safety-curve")
def safety_curve(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    try:items=[propose_plan(db,seller_id,target_prob=target,persist=False) for target in (Decimal(".40"),Decimal(".30"),Decimal(".20"),Decimal(".10"))]
    except ValueError as exc:raise HTTPException(409,str(exc))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="plan.safety_curve.read",tier="T0_READ",payload={"targets":[x["target_probability"] for x in items]},policy_decision="ALLOW")
    db.commit()
    return {"seller_id":seller_id,"default_target_probability":str(get_settings().kosh_plan_target_prob),"items":items}

@router.post("/plans")
def create_plan(seller_id:int,payload:PlanIn=PlanIn(),db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=propose_plan(db,seller_id,target_prob=payload.target_probability,loan_repayment_date=payload.loan_repayment_date)
    except ValueError as exc:raise HTTPException(409,str(exc))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="plan.propose",tier="T1_DRAFT",payload={"plan_id":row.id,"target_probability":row.planning_details["target_probability"]},policy_decision="ALLOW");db.commit();return {"plan_id":row.id}
@router.get("/plans/latest")
def latest(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=db.scalar(select(KoshPlan).where(KoshPlan.seller_id==seller_id).order_by(KoshPlan.id.desc()).limit(1))
    if not row:raise HTTPException(404,"No plan")
    return _plan_out(db,row)
@router.get("/plan")
def plan_compatibility(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=db.scalar(select(KoshPlan).where(KoshPlan.seller_id==seller_id).order_by(KoshPlan.id.desc()).limit(1))
    return _plan_out(db,row) if row else {"seller_id":seller_id,"status":"NOT_IMPLEMENTED","items":[]}
@router.get("/plans/{plan_id}")
def detail(seller_id:int,plan_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=db.scalar(select(KoshPlan).where(KoshPlan.id==plan_id,KoshPlan.seller_id==seller_id))
    if not row:raise HTTPException(404,"Plan not found")
    return _plan_out(db,row)
