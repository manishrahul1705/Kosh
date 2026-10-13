"""Cost-minimizing cash plans with same-seed forecast evidence."""
from __future__ import annotations
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from sqlalchemy import select
from app.database.kosh_models import KoshFinancingEvaluation,KoshFinancingResult,KoshForecastRun,KoshForecastWeek,KoshPlan,KoshPlanLine
from app.finance.forecast import load_inputs,simulate,week_bounds
from app.finance.costs import financing_quote
from app.lending.catalogue import load_catalogue
from app.core.config import get_settings


def optimize_levers(required:int,levers:list[dict],*,solver:str="AUTO")->tuple[str,list[dict]]:
    """One net-cash constraint and independent caps: fractional knapsack is exact.

    LP and greedy use cost per net paise, not an annual rate as an absolute cost.
    Integer rounding is repaired through the same deterministic greedy allocation.
    """
    usable=sorted((x for x in levers if x["status"]=="MATCHED" and x["cap"]>0 and x.get("net_factor",1)>0),key=lambda x:(Decimal(str(x["unit_cost"]))/Decimal(str(x.get("net_factor",1))),x["product_id"],x.get("scope") or ""))
    if required<=0:return "GREEDY",[]
    method="GREEDY"
    if solver!="GREEDY" and usable:
        try:
            from scipy.optimize import linprog
        except ImportError:
            if solver=="LINPROG":raise
        else:
            result=linprog([float(x["unit_cost"]) for x in usable],A_ub=[[-float(x.get("net_factor",1)) for x in usable]],b_ub=[-required],bounds=[(0,x["cap"]) for x in usable],method="highs")
            if result.success:method="LINPROG"
            elif solver=="LINPROG":raise ValueError(result.message)
    # The single constraint has the same optimum as LP, with deterministic ties.
    remaining=Decimal(required);chosen=[]
    for item in usable:
        factor=Decimal(str(item.get("net_factor",1)))
        amount=min(int((remaining/factor).to_integral_value(rounding=ROUND_CEILING)),item["cap"])
        if amount>0:chosen.append({**item,"amount":amount});remaining-=Decimal(amount)*factor
        if remaining<=0:break
    return method,chosen


def _arrival(as_of,business_days):
    result=as_of
    for _ in range(business_days):
        result+=timedelta(days=1)
        while result.weekday()>=5:result+=timedelta(days=1)
    return result


def plan_scenario(inputs,run,chosen,products):
    extras=[];reductions={}
    for line in chosen:
        product=products[line["product_id"]];quote=financing_quote(product,line["amount"])
        arrival=_arrival(run.as_of_date,line["arrival_business_days"])
        extras.append({"date":arrival.isoformat(),"amount_paise":quote["net_proceeds_paise"]})
        if line["scope"] and line["scope"].startswith("invoice:"):
            invoice_id=int(line["scope"].split(":")[1])
            reductions[invoice_id]=reductions.get(invoice_id,0)+line["amount"]
        elif line["product_id"] not in {"COLLECTIONS_PUSH","SUPPLIER_TERM_EXTENSION"}:
            # Fees withheld at arrival; principal + interest repaid at tenor end.
            fee=line["amount"]-quote["net_proceeds_paise"]
            extras.append({"date":(arrival+timedelta(days=quote["days"])).isoformat(),"amount_paise":-(line["amount"]+quote["cost_paise"]-fee)})
    return simulate(inputs,as_of=run.as_of_date,n_paths=run.n_paths,seed=run.seed,include_forecast_sales=run.include_forecast_sales,buffer_paise=run.buffer_paise,extra_inflows=extras,invoice_amount_reductions=reductions)


def propose_plan(db,seller_id:int)->KoshPlan:
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()).limit(1))
    if not run:raise ValueError("No successful forecast")
    weeks=db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id).order_by(KoshForecastWeek.week_index)).all()
    threshold=get_settings().kosh_alert_threshold
    alert=next((w for w in weeks if w.prob_below_buffer>=threshold),None)
    target=alert.week_index if alert else 1
    percentile=get_settings().kosh_plan_percentile
    w=weeks[target-1]
    weight=Decimal(percentile-10)/40
    balance=w.p50_closing_balance_paise if percentile==50 else int(Decimal(w.p10_closing_balance_paise)+Decimal(w.p50_closing_balance_paise-w.p10_closing_balance_paise)*weight)
    required=max(0,run.buffer_paise-balance) if alert else 0
    evaluation=db.scalar(select(KoshFinancingEvaluation).where(KoshFinancingEvaluation.seller_id==seller_id,KoshFinancingEvaluation.forecast_run_id==run.id).order_by(KoshFinancingEvaluation.id.desc()).limit(1))
    if not evaluation:raise ValueError("Evaluate financing against the latest forecast first")
    rows=db.scalars(select(KoshFinancingResult).where(KoshFinancingResult.evaluation_id==evaluation.id)).all()
    products={p["id"]:p for p in load_catalogue()};levers=[]
    for row in rows:
        quote=financing_quote(products[row.product_id],row.max_amount_paise)
        factor=Decimal(quote["net_proceeds_paise"])/row.max_amount_paise if row.max_amount_paise else Decimal(0)
        timely=_arrival(run.as_of_date,row.arrival_business_days)<=w.week_end
        levers.append({"product_id":row.product_id,"status":row.status,"cap":row.max_amount_paise if timely else 0,"unit_cost":Decimal(quote["cost_paise"])/row.max_amount_paise if row.max_amount_paise else Decimal(0),"net_factor":factor,"rate":Decimal(quote["effective_annual_rate"]),"scope":row.scope,"arrival_business_days":row.arrival_business_days})
    method,chosen=optimize_levers(required,levers)
    inputs=load_inputs(db,seller_id,run.as_of_date)
    after=plan_scenario(inputs,run,chosen,products)
    before=[w.prob_below_buffer for w in weeks];after_p=[w["prob_below_buffer"] for w in after["weeks"]]
    total=sum(financing_quote(products[x["product_id"]],x["amount"])["cost_paise"] for x in chosen)
    principal=sum(x["amount"] for x in chosen)
    baseline=financing_quote(products["NBFC_UNSECURED_BUSINESS_LOAN"],principal)["cost_paise"]
    why=f"Lowest absolute cost per net paise arriving by alert week {target}, subject to documented caps. Only MATCHED options are eligible."
    selected={(x["product_id"],x["scope"]) for x in chosen}
    skipped=[]
    for lever in levers:
        if (lever["product_id"],lever["scope"]) in selected:continue
        reason="requires review or failed eligibility" if lever["status"]!="MATCHED" else "cannot arrive by the alert week" if lever["cap"]==0 else "costs more per net paise than the selected available capacity"
        skipped.append(f"{lever['product_id']}: {reason}.")
    why+=" "+" ".join(skipped)
    plan=KoshPlan(seller_id=seller_id,forecast_run_id=run.id,forecast_fingerprint=run.input_fingerprint,method=method,status="PROPOSED",total_cost_paise=total,baseline_cost_paise=baseline,before_probabilities=before,after_probabilities=after_p);db.add(plan);db.flush()
    tiers={"COLLECTIONS_PUSH":"T2","SUPPLIER_TERM_EXTENSION":"T2"}
    for x in chosen:
        quote=financing_quote(products[x["product_id"]],x["amount"])
        arrival_week=(_arrival(run.as_of_date,x["arrival_business_days"])-week_bounds(run.as_of_date)[0]).days//7+1
        db.add(KoshPlanLine(plan_id=plan.id,product_id=x["product_id"],scope_ids=[int(x["scope"].split(":")[1])] if x["scope"] and ":" in x["scope"] else [],amount_paise=x["amount"],arrival_week=arrival_week,cost_paise=quote["cost_paise"],effective_annual_rate=quote["effective_annual_rate"],required_tier=tiers.get(x["product_id"],"T3"),evidence=[{"why_this_plan":why,"target_week":target}],status="PROPOSED"))
    return plan
