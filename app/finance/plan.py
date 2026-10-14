"""Cost-minimizing cash plans with same-seed forecast evidence."""
from __future__ import annotations
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from sqlalchemy import select
from app.database.kosh_models import KoshFinancingEvaluation,KoshFinancingResult,KoshForecastRun,KoshForecastWeek,KoshPlan,KoshPlanLine,KoshInvoice
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
            # HiGHS receives only dimensionless fractions and normalized ratios.
            # Money stays integer/Decimal, including reconstruction of allocations.
            scale=Decimal(max(required,sum(x["cap"] for x in usable)))
            objective=[Decimal(str(x["unit_cost"]))*x["cap"] for x in usable]
            cost_scale=max(max(objective),Decimal(1))
            result=linprog([float(cost/cost_scale) for cost in objective],A_ub=[[-float(Decimal(x["cap"])*Decimal(str(x.get("net_factor",1)))/scale) for x in usable]],b_ub=[-float(Decimal(required)/scale)],bounds=[(0,1)]*len(usable),method="highs")
            if result.success:
                chosen=[{**item,"amount":min(item["cap"],int((Decimal(item["cap"])*Decimal(str(fraction))).to_integral_value(rounding=ROUND_CEILING)))} for item,fraction in zip(usable,result.x) if fraction>0]
                if sum(Decimal(x["amount"])*Decimal(str(x.get("net_factor",1))) for x in chosen)>=required:
                    return "LINPROG",chosen
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


def line_quote(products,line):
    return financing_quote(products[line["product_id"]],line["amount"],days=line.get("days"))


def plan_scenario(inputs,run,chosen,products):
    extras=[];reductions={}
    for line in chosen:
        product=products[line["product_id"]];quote=line_quote(products,line)
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


def validate_and_complete(chosen,levers,check,*,target_week,threshold,target_prob=None):
    """Check each extension with the same seed; return no false validity claim."""
    chosen=[dict(x) for x in chosen]
    def valid(result):
        probabilities=[Decimal(str(w["prob_below_buffer"])) for w in result["weeks"]]
        if target_prob is None:return probabilities[target_week-1]<Decimal(str(threshold))
        return probabilities[target_week-1]<=Decimal(str(target_prob)) and all(p<Decimal(str(threshold)) for p in probabilities)
    after=check(chosen)
    ordered=sorted((x for x in levers if x["status"]=="MATCHED" and x["cap"]>0),key=lambda x:(Decimal(str(x["unit_cost"]))/Decimal(str(x.get("net_factor",1))),x["product_id"],x.get("scope") or ""))
    for lever in ordered:
        if valid(after):break
        existing=next((x for x in chosen if (x["product_id"],x["scope"])==(lever["product_id"],lever["scope"])),None)
        if existing and existing["amount"]>=lever["cap"]:continue
        if existing:existing["amount"]=lever["cap"]
        else:chosen.append({**lever,"amount":lever["cap"]})
        after=check(chosen)
    if not valid(after):return chosen,after,"INSUFFICIENT"
    # Remove surplus paid capacity, most expensive first, to integer-paise precision.
    # Zero-cost capacity remains available and carries disclosed relationship risk.
    for line in sorted(chosen,key=lambda x:(x["unit_cost"],x["product_id"]),reverse=True):
        if line["unit_cost"]<=0:continue
        lo=0;hi=line["amount"]
        while lo<hi:
            mid=(lo+hi)//2;line["amount"]=mid
            trial=check(chosen)
            if valid(trial):hi=mid
            else:lo=mid+1
        line["amount"]=lo
    chosen=[x for x in chosen if x["amount"]>0];after=check(chosen)
    return chosen,after,("VALID" if target_prob is not None else "PROPOSED") if valid(after) else "INSUFFICIENT"


def reserve_shared_invoice_capacity(levers):
    # Reserve zero-cost collections capacity on shared invoices before discounting.
    # This prevents financing the same receivable twice across separate products.
    reserved={x["scope"]:x["cap"] for x in levers if x["product_id"]=="COLLECTIONS_PUSH" and x["status"]=="MATCHED" and x["cap"]>0}
    for lever in levers:
        if lever["product_id"]=="TREDS_INVOICE_DISCOUNTING":lever["cap"]=max(0,lever["cap"]-reserved.get(lever["scope"],0))


def propose_plan(db,seller_id:int,*,target_prob=None,persist=True,loan_repayment_date=None)->KoshPlan|dict:
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()).limit(1))
    if not run:raise ValueError("No successful forecast")
    weeks=db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id).order_by(KoshForecastWeek.week_index)).all()
    threshold=get_settings().kosh_alert_threshold
    target_prob=Decimal(str(target_prob if target_prob is not None else get_settings().kosh_plan_target_prob))
    if not 0<=target_prob<Decimal(str(threshold)):raise ValueError("Plan target must be below the alert threshold")
    alert=next((w for w in weeks if w.prob_below_buffer>=threshold),None)
    critical=alert or max(weeks,key=lambda week:(week.prob_below_buffer,-week.week_index))
    target=critical.week_index
    percentile=get_settings().kosh_plan_percentile
    w=weeks[target-1]
    weight=Decimal(percentile-10)/40
    balance=w.p50_closing_balance_paise if percentile==50 else int(Decimal(w.p10_closing_balance_paise)+Decimal(w.p50_closing_balance_paise-w.p10_closing_balance_paise)*weight)
    required=max(0,run.buffer_paise-balance) if Decimal(str(critical.prob_below_buffer))>target_prob else 0
    evaluation=db.scalar(select(KoshFinancingEvaluation).where(KoshFinancingEvaluation.seller_id==seller_id,KoshFinancingEvaluation.forecast_run_id==run.id).order_by(KoshFinancingEvaluation.id.desc()).limit(1))
    if not evaluation:raise ValueError("Evaluate financing against the latest forecast first")
    rows=db.scalars(select(KoshFinancingResult).where(KoshFinancingResult.evaluation_id==evaluation.id)).all()
    products={p["id"]:p for p in load_catalogue()};levers=[]
    for row in rows:
        product=products[row.product_id]
        arrival=_arrival(run.as_of_date,row.arrival_business_days)
        repayment=loan_repayment_date or arrival+timedelta(days=int(product["cost_model"]["tenor_days"]))
        assumption="Planned bullet repayment on the stated date; actual drawn calendar days, not the options quote basis."
        if row.product_id=="TREDS_INVOICE_DISCOUNTING" and row.scope:
            invoice=db.scalar(select(KoshInvoice).where(KoshInvoice.id==int(row.scope.split(":")[1]),KoshInvoice.seller_id==seller_id))
            if not invoice:continue
            repayment=invoice.due_date
            assumption="Invoice matures on its recorded due date; discounting tenor starts on the funding date."
        relationship=row.product_id in {"COLLECTIONS_PUSH","SUPPLIER_TERM_EXTENSION"}
        if relationship:
            repayment=None;days=0
            assumption="Timing-only operational lever; no financing tenor or repayment obligation."
        else:days=(repayment-arrival).days
        if days<=0 and not relationship:continue
        quote=financing_quote(product,row.max_amount_paise,days=days)
        factor=Decimal(quote["net_proceeds_paise"])/row.max_amount_paise if row.max_amount_paise else Decimal(0)
        timely=_arrival(run.as_of_date,row.arrival_business_days)<=w.week_end
        levers.append({"product_id":row.product_id,"status":row.status,"cap":row.max_amount_paise if timely else 0,"unit_cost":Decimal(quote["cost_paise"])/row.max_amount_paise if row.max_amount_paise else Decimal(0),"net_factor":factor,"rate":Decimal(quote["effective_annual_rate"]),"scope":row.scope,"arrival_business_days":row.arrival_business_days,"days":days,"funding_date":arrival.isoformat(),"repayment_date":repayment.isoformat() if repayment else None,"repayment_assumption":assumption})
    reserve_shared_invoice_capacity(levers)
    method,chosen=optimize_levers(required,levers)
    inputs=load_inputs(db,seller_id,run.as_of_date,include_addon_events=run.params.get("include_addon_events",True),include_customer_history=run.params.get("include_customer_history",False),include_revenue_signal=run.params.get("include_revenue_signal",False))
    chosen,after,status=validate_and_complete(chosen,levers,lambda lines:plan_scenario(inputs,run,lines,products),target_week=target,threshold=threshold,target_prob=target_prob)
    before=[w.prob_below_buffer for w in weeks];after_p=[w["prob_below_buffer"] for w in after["weeks"]]
    total=sum(line_quote(products,x)["cost_paise"] for x in chosen)
    # The comparison must meet the same safety target and horizon gate, using
    # the same free collections capacity, fees, arrival and repayment cash flows.
    baseline_levers=[x for x in levers if x["product_id"] in {"COLLECTIONS_PUSH","NBFC_UNSECURED_BUSINESS_LOAN"}]
    _,baseline_chosen=optimize_levers(required,baseline_levers)
    baseline_chosen,baseline_after,baseline_status=validate_and_complete(baseline_chosen,baseline_levers,lambda lines:plan_scenario(inputs,run,lines,products),target_week=target,threshold=threshold,target_prob=target_prob)
    baseline=sum(line_quote(products,x)["cost_paise"] for x in baseline_chosen) if baseline_status=="VALID" else 0
    details={"target_probability":str(target_prob),"alert_threshold":str(threshold),"alert_week":target,"baseline_status":baseline_status,"baseline_after_probabilities":[w["prob_below_buffer"] for w in baseline_after["weeks"]],"baseline_lines":[{"product_id":x["product_id"],"amount_paise":x["amount"],"scope":x["scope"],"days":x["days"],"funding_date":x["funding_date"],"repayment_date":x["repayment_date"]} for x in baseline_chosen]}
    why=f"Allocate the least-cost net cash arriving by alert week {target}, subject to documented independent caps. The allocation is exact for this single net-cash constraint; probability is separately verified by the same-seed forecast. Only MATCHED options are eligible."
    selected={(x["product_id"],x["scope"]) for x in chosen}
    skipped=[]
    for lever in levers:
        if (lever["product_id"],lever["scope"]) in selected:continue
        reason="requires review or failed eligibility" if lever["status"]!="MATCHED" else "cannot arrive by the alert week" if lever["cap"]==0 else "costs more per net paise than the selected available capacity"
        skipped.append(f"{lever['product_id']}: {reason}.")
    why+=" "+" ".join(skipped)
    why+=f" Same-seed forecast at week {target}: {after_p[target-1]:.4f}, required at most {target_prob:.4f}; every horizon week below {threshold:.4f}. Paid capacity trimmed to the smallest valid paise amount." if status=="VALID" else " Available eligible capacity cannot bring the target and horizon safety conditions; this plan is INSUFFICIENT."
    details["why_this_plan"]=why
    if not persist:
        return {"target_probability":str(target_prob),"status":status,"method":method,"total_cost_paise":total,"baseline_cost_paise":baseline,"planning_details":details,"after_probabilities":after_p,"alert_week_probability":after_p[target-1],"why_this_plan":why,"lines":[{"product_id":x["product_id"],"scope":x["scope"],"funding_date":x["funding_date"],"repayment_date":x["repayment_date"],"repayment_assumption":x["repayment_assumption"],**line_quote(products,x)} for x in chosen]}
    plan=KoshPlan(seller_id=seller_id,forecast_run_id=run.id,forecast_fingerprint=run.input_fingerprint,method=method,status=status,planning_details=details,total_cost_paise=total,baseline_cost_paise=baseline,before_probabilities=before,after_probabilities=after_p);db.add(plan);db.flush()
    tiers={"COLLECTIONS_PUSH":"T2","SUPPLIER_TERM_EXTENSION":"T2"}
    for x in chosen:
        quote=line_quote(products,x)
        arrival_week=(_arrival(run.as_of_date,x["arrival_business_days"])-week_bounds(run.as_of_date)[0]).days//7+1
        db.add(KoshPlanLine(plan_id=plan.id,product_id=x["product_id"],scope_ids=[int(x["scope"].split(":")[1])] if x["scope"] and ":" in x["scope"] else [],amount_paise=x["amount"],arrival_week=arrival_week,cost_paise=quote["cost_paise"],effective_annual_rate=quote["effective_annual_rate"],required_tier=tiers.get(x["product_id"],"T3"),evidence=[{"why_this_plan":why,"target_week":target,"threshold":threshold,"target_probability":str(target_prob),"days":x["days"],"funding_date":x["funding_date"],"repayment_date":x["repayment_date"],"repayment_assumption":x["repayment_assumption"]}],status=status))
    return plan
