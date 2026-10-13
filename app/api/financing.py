"""Seller-authorized financing evaluation and plan endpoints."""
from datetime import date
from decimal import Decimal
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit,require_seller_read
from app.audit.ledger import append_event
from app.core.config import get_settings
from app.database.kosh_models import KoshFinancingEvaluation,KoshFinancingResult,KoshPlan,KoshPlanLine
from app.finance.plan import propose_plan
from app.lending.catalogue import load_catalogue
from app.lending.service import run_evaluation

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}",tags=["kosh-financing"])
SORT_RULE="sorted by effective annual cost, lowest first; no provider pays for placement"
def _as_of():return date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat())
def _latest_eval(db,seller):return db.scalar(select(KoshFinancingEvaluation).where(KoshFinancingEvaluation.seller_id==seller).order_by(KoshFinancingEvaluation.id.desc()).limit(1))
def _result(row,products):
    product=products[row.product_id];return {"product_id":row.product_id,"display_name":product["display_name"],"provider_label":product["provider_label"],"scope":row.scope,"status":row.status,"max_amount_paise":row.max_amount_paise,"effective_annual_rate":row.effective_annual_rate,"arrival_business_days":row.arrival_business_days,"reasons":row.reasons,"evidence":row.evidence,"assumption":product["cost_model"].get("assumption",False),"verify_before_relying":any(not c.get("source",{}).get("verified",False) for c in product["criteria"])}
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
def _plan_out(db,row):
    lines=db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id==row.id)).all();return {"id":row.id,"seller_id":row.seller_id,"forecast_run_id":row.forecast_run_id,"forecast_fingerprint":row.forecast_fingerprint,"method":row.method,"status":row.status,"total_cost_paise":row.total_cost_paise,"baseline_cost_paise":row.baseline_cost_paise,"before_probabilities":row.before_probabilities,"after_probabilities":row.after_probabilities,"lines":[{c.name:getattr(x,c.name) for c in x.__table__.columns} for x in lines]}
@router.post("/plans")
def create_plan(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=propose_plan(db,seller_id)
    except ValueError as exc:raise HTTPException(409,str(exc))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="plan.propose",tier="T1_DRAFT",payload={"plan_id":row.id},policy_decision="ALLOW");db.commit();return {"plan_id":row.id}
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
