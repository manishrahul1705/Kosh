"""Approval-gated sandbox execution and same-seed actual cash reforecast."""
from sqlalchemy import select
from decimal import Decimal
from app.actions.approvals import consume,ActionError,denied
from app.audit.ledger import append_event
from app.audit.verify import verify_chain
from app.database.kosh_models import KoshForecastRun,KoshForecastWeek,KoshAlert,KoshPlan,KoshPlanLine
from app.finance.forecast import load_inputs,simulate,fingerprint
from app.finance.alerts import build_alert
from app.sandbox.adapters import run,reconcile,AdapterError
from app.utils.dates import utcnow

def persist_forecast(db,*,seller_id,actor_id,basis,result,inputs):
    params={"include_addon_events":basis.params.get("include_addon_events",True),"n_paths":basis.n_paths,"seed":basis.seed,"include_forecast_sales":basis.include_forecast_sales}
    digest=fingerprint(inputs,{**params,"as_of_date":basis.as_of_date,"buffer_paise":basis.buffer_paise})
    row=KoshForecastRun(seller_id=seller_id,as_of_date=basis.as_of_date,horizon_weeks=13,n_paths=basis.n_paths,seed=basis.seed,params=params,input_fingerprint=digest,include_forecast_sales=basis.include_forecast_sales,buffer_paise=basis.buffer_paise,status="SUCCESS",created_by_user_id=actor_id)
    db.add(row);db.flush()
    for week in result["weeks"]:db.add(KoshForecastWeek(run_id=row.id,**week))
    for previous in db.scalars(select(KoshAlert).where(KoshAlert.seller_id==seller_id,KoshAlert.status=="OPEN")):previous.status="SUPERSEDED"
    from app.core.config import get_settings
    alert=build_alert(inputs,result,as_of=basis.as_of_date,threshold=get_settings().kosh_alert_threshold)
    if alert:db.add(KoshAlert(seller_id=seller_id,run_id=row.id,status="OPEN",**{key:alert[key] for key in ("week_index","probability","expected_shortfall_paise","peak_expected_shortfall_paise","causes")}))
    append_event(db,seller_id=seller_id,actor_type="SYSTEM",actor_id=str(actor_id),action="forecast.after_execution",tier="T0",payload={"run_id":row.id,"seed":basis.seed,"input_fingerprint":digest},policy_decision="ALLOW")
    return row

def execute(db,*,seller_id,intent_id,actor_id,token):
    intent,artifact=consume(db,seller_id=seller_id,intent_id=intent_id,actor_id=actor_id,token=token)
    if not verify_chain(db).valid:denied(db,intent,actor_id,"AUDIT_CHAIN_INVALID","Audit integrity must be valid before execution.",new_status="BLOCKED")
    basis=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()).limit(1))
    if basis is None:denied(db,intent,actor_id,"FORECAST_REQUIRED","A successful forecast is required.")
    before_inputs=load_inputs(db,seller_id,basis.as_of_date,include_addon_events=basis.params.get("include_addon_events",True))
    kwargs={"as_of":basis.as_of_date,"n_paths":basis.n_paths,"seed":basis.seed,"include_forecast_sales":basis.include_forecast_sales,"buffer_paise":basis.buffer_paise}
    before=simulate(before_inputs,**kwargs)
    intent.status="EXECUTING";intent.updated_at=utcnow()
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="intent.executing",tier=intent.tier,payload={"intent_id":intent.id,"params_hash":intent.params_hash},policy_decision="ALLOW",approval_id=artifact.jti)
    try:execution=run(db,intent)
    except AdapterError as exc:
        intent.status="FAILED";append_event(db,seller_id=seller_id,actor_type="SYSTEM",actor_id=None,action="intent.failed",tier=intent.tier,payload={"intent_id":intent.id,"reason":str(exc)},policy_decision="DENY")
        raise ActionError("SANDBOX_EXECUTION",str(exc),409)
    if execution.status!="SETTLED":
        intent.status="FAILED";append_event(db,seller_id=seller_id,actor_type="SYSTEM",actor_id=None,action="intent.failed",tier=intent.tier,payload={"intent_id":intent.id,"execution_id":execution.id,"reason":execution.error},policy_decision="DENY")
        return execution
    if reconcile(db,seller_id,execution.id)["status"]!="MATCHED":
        intent.status="FAILED";append_event(db,seller_id=seller_id,actor_type="SYSTEM",actor_id=None,action="security.reconciliation_mismatch",tier=intent.tier,payload={"intent_id":intent.id,"execution_id":execution.id},policy_decision="DENY")
        raise ActionError("RECONCILIATION_MISMATCH","Sandbox ledger does not match expected entries.",409)
    intent.status="SUCCEEDED";intent.executed_at=utcnow()
    line=db.get(KoshPlanLine,intent.plan_line_id) if intent.plan_line_id is not None else None
    if line is not None:line.status="EXECUTED"
    # Flush settled state before the read-only overlay loads it.
    db.flush()
    after_inputs=load_inputs(db,seller_id,basis.as_of_date,include_addon_events=basis.params.get("include_addon_events",True));after=simulate(after_inputs,**kwargs)
    after_run=persist_forecast(db,seller_id=seller_id,actor_id=actor_id,basis=basis,result=after,inputs=after_inputs)
    if line is None:
        from app.database.kosh_models import KoshAddonDraft
        draft=db.get(KoshAddonDraft,intent.params["draft_id"]);draft.status="EXECUTED"
        execution.result={**execution.result,"before_forecast_run_id":basis.id,"after_forecast_run_id":after_run.id,"before_probabilities":[w["prob_below_buffer"] for w in before["weeks"]],"after_probabilities":[w["prob_below_buffer"] for w in after["weeks"]],"target_met":None,"seed":basis.seed,"as_of_date":basis.as_of_date.isoformat()}
        append_event(db,seller_id=seller_id,actor_type="SYSTEM",actor_id=None,action="addon.intent.succeeded",tier=intent.tier,payload={"intent_id":intent.id,"execution_id":execution.id,"draft_id":draft.id},policy_decision="ALLOW")
        return execution
    plan=db.get(KoshPlan,line.plan_id);details=dict(plan.planning_details)
    before_probabilities=[w["prob_below_buffer"] for w in before["weeks"]];after_probabilities=[w["prob_below_buffer"] for w in after["weeks"]]
    target_week=details["alert_week"];target=Decimal(details["target_probability"]);threshold=Decimal(details["alert_threshold"])
    target_met=Decimal(str(after_probabilities[target_week-1]))<=target and all(Decimal(str(p))<threshold for p in after_probabilities)
    details.setdefault("proposal_after_probabilities",plan.after_probabilities)
    details["actual_execution"]={"forecast_run_id":after_run.id,"before_probabilities":before_probabilities,"after_probabilities":after_probabilities,"target_met":target_met,"source":"SANDBOX"}
    details["why_this_plan"]=("Sandbox execution meets the chosen safety target and every horizon week remains below the alert threshold." if target_met else "Executed cash effects have not met the chosen safety conditions. This plan is INSUFFICIENT; re-evaluate options. A sent reminder is not evidence of payment.")
    plan.planning_details=details;plan.after_probabilities=after_probabilities;plan.status="VALID" if target_met else "INSUFFICIENT"
    execution.result={**execution.result,"before_forecast_run_id":basis.id,"after_forecast_run_id":after_run.id,"before_probabilities":before_probabilities,"after_probabilities":after_probabilities,"target_met":target_met,"seed":basis.seed,"as_of_date":basis.as_of_date.isoformat()}
    append_event(db,seller_id=seller_id,actor_type="SYSTEM",actor_id=None,action="intent.succeeded",tier=intent.tier,payload={"intent_id":intent.id,"execution_id":execution.id,"after_forecast_run_id":after_run.id,"target_met":target_met},policy_decision="ALLOW")
    return execution
