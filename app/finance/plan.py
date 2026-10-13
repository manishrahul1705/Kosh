"""Cost-minimizing, forecast-proven cash gap plans."""
from __future__ import annotations
from datetime import timedelta
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import func,select
from app.database.kosh_models import KoshFinancingEvaluation,KoshFinancingResult,KoshForecastRun,KoshForecastWeek,KoshInvoice,KoshCounterparty,KoshPlan,KoshPlanLine
from app.finance.forecast import load_inputs,simulate
from app.core.config import get_settings

def _cost(amount:int,rate:Decimal,days:int=90)->int:return int((Decimal(amount)*rate*Decimal(days)/Decimal(365)).quantize(Decimal("1"),rounding=ROUND_HALF_UP))

def optimize_levers(required:int,levers:list[dict])->tuple[str,list[dict]]:
    usable=[x for x in levers if x["status"]=="MATCHED" and x["cap"]>0]
    try:
        from scipy.optimize import linprog
        result=linprog([float(x["unit_cost"]) for x in usable],A_ub=[[-1.0]*len(usable)],b_ub=[-required],bounds=[(0,x["cap"]) for x in usable],method="highs")
        if result.success:return "LINPROG",[{**x,"amount":int(round(v))} for x,v in zip(usable,result.x) if v>=1]
    except (ImportError,ValueError):pass
    remaining=required;chosen=[]
    for item in sorted(usable,key=lambda x:(x["unit_cost"],x["product_id"])):
        amount=min(remaining,item["cap"])
        if amount:chosen.append({**item,"amount":amount});remaining-=amount
        if remaining<=0:break
    return "GREEDY",chosen

def propose_plan(db,seller_id:int)->KoshPlan:
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()).limit(1))
    if not run:raise ValueError("No successful forecast")
    weeks=db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id).order_by(KoshForecastWeek.week_index)).all();percentile=get_settings().kosh_plan_percentile
    def planning_balance(w):
        if percentile==50:return w.p50_closing_balance_paise
        weight=Decimal(percentile-10)/Decimal(40)
        return int((Decimal(w.p10_closing_balance_paise)+Decimal(w.p50_closing_balance_paise-w.p10_closing_balance_paise)*weight).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    required=max(max(0,run.buffer_paise-planning_balance(w)) for w in weeks)
    evaluation_id=db.scalar(select(func.max(KoshFinancingResult.evaluation_id)).join(KoshFinancingEvaluation,KoshFinancingEvaluation.id==KoshFinancingResult.evaluation_id).where(KoshFinancingEvaluation.seller_id==seller_id))
    rows=db.scalars(select(KoshFinancingResult).where(KoshFinancingResult.evaluation_id==evaluation_id)).all() if evaluation_id else []
    levers=[{"product_id":r.product_id,"status":r.status,"cap":r.max_amount_paise,"unit_cost":float(Decimal(r.effective_annual_rate or "0")*Decimal(90)/Decimal(365)),"rate":Decimal(r.effective_annual_rate or "0"),"scope":r.scope} for r in rows]
    method,chosen=optimize_levers(required,levers);extras=[];accelerated=set();reductions={}
    arrival=run.as_of_date+timedelta(days=3)
    for line in chosen:
        cost=_cost(line["amount"],line["rate"])
        if line["scope"] and line["scope"].startswith("invoice:"):
            invoice_id=int(line["scope"].split(":")[1])
            if line["product_id"]=="TREDS_INVOICE_DISCOUNTING":accelerated.add(invoice_id)
            elif line["product_id"]=="COLLECTIONS_PUSH":reductions[invoice_id]=line["amount"]
        extras.append({"date":arrival.isoformat(),"amount_paise":line["amount"]-cost})
    inputs=load_inputs(db,seller_id,run.as_of_date);after=simulate(inputs,as_of=run.as_of_date,n_paths=run.n_paths,seed=run.seed,include_forecast_sales=run.include_forecast_sales,buffer_paise=run.buffer_paise,extra_inflows=extras,accelerated_invoice_ids=accelerated,invoice_amount_reductions=reductions)
    before=[w.prob_below_buffer for w in weeks];after_p=[w["prob_below_buffer"] for w in after["weeks"]]
    total=sum(_cost(x["amount"],x["rate"]) for x in chosen);baseline=_cost(required,Decimal("0.24"))
    plan=KoshPlan(seller_id=seller_id,forecast_run_id=run.id,forecast_fingerprint=run.input_fingerprint,method=method,status="PROPOSED",total_cost_paise=total,baseline_cost_paise=baseline,before_probabilities=before,after_probabilities=after_p);db.add(plan);db.flush()
    tiers={"COLLECTIONS_PUSH":"T2","SUPPLIER_TERM_EXTENSION":"T2"}
    for x in chosen:db.add(KoshPlanLine(plan_id=plan.id,product_id=x["product_id"],scope_ids=[int(x["scope"].split(":")[1])] if x["scope"] and ":" in x["scope"] else [],amount_paise=x["amount"],arrival_week=1,cost_paise=_cost(x["amount"],x["rate"]),effective_annual_rate=str(x["rate"]),required_tier=tiers.get(x["product_id"],"T3"),evidence=[],status="PROPOSED"))
    return plan

