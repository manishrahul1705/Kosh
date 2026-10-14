"""The sole intent factory: derives immutable parameters from trusted plan lines."""
import uuid
from decimal import Decimal
from sqlalchemy import select
from app.audit.ledger import append_event
from app.database.session import reserve_sqlite_writer
from app.database.kosh_models import KoshActionIntent,KoshPlan,KoshPlanLine,KoshInvoice,KoshForecastRun
from app.actions.integrity import current_hash
from app.actions.read import day_used
from app.policy.rules import evaluate,TIERS
from app.policy.controls import context
from app.utils.dates import utcnow

PRODUCT_ACTIONS={"COLLECTIONS_PUSH":"COLLECTIONS_REMINDER","SUPPLIER_TERM_EXTENSION":"SUPPLIER_TERM_REQUEST","TREDS_INVOICE_DISCOUNTING":"TREDS_FINANCE","BANK_OD_DRAWDOWN":"OD_DRAWDOWN","CGTMSE_BACKED_WC_LOAN":"LOAN_APPLICATION","MUDRA_LOAN":"LOAN_APPLICATION","NBFC_UNSECURED_BUSINESS_LOAN":"LOAN_APPLICATION"}
REGISTERED_MODULES={"collections","sales","procurement","pricing","customer_intelligence","revenue","reports","tender_to_cash"}

def decision_for(db,intent,*,phase="propose",actor_role=None,approved=False,otp_verified=False,consent_valid=None):
    from app.finance.modules import enabled
    from app.policy.rules import PolicyDecision
    feature=intent.params.get('feature_module') or (intent.source.split(':',1)[1] if intent.source.startswith('ADDON:') else {'COLLECTIONS_PUSH':'collections','SUPPLIER_TERM_EXTENSION':'procurement'}.get(intent.params.get('product_code')))
    if feature and not enabled(db,intent.seller_id,feature):return PolicyDecision(intent.tier,'DENY',('MODULE_DISABLED',),('This module is disabled for the seller.',))
    if consent_valid is None:
        from app.consent.sharing import active
        consent_valid=active(db,seller_id=intent.seller_id,purpose=intent.params.get("sharing_purpose"),recipient_id=intent.params.get("recipient_id"),fields=intent.params.get("sharing_fields",[])) is not None if intent.params.get("sharing_fields") else False
    return evaluate(intent.action_type,intent.params,context(db,intent.seller_id,day_used_paise=day_used(db,intent.seller_id,exclude_intent_id=intent.id),actor_role=actor_role,approved=approved,otp_verified=otp_verified,consent_valid=consent_valid),phase=phase,origin=intent.source)

def create_from_plan_line(db,*,seller_id,plan_line_id,creator_id,source="PLANNER"):
    if source!="PLANNER" and source not in {f"ADDON:{name}" for name in REGISTERED_MODULES}:raise ValueError("UNREGISTERED_SOURCE")
    reserve_sqlite_writer(db,renew_read=True)
    line=db.scalar(select(KoshPlanLine).join(KoshPlan,KoshPlan.id==KoshPlanLine.plan_id).where(KoshPlanLine.id==plan_line_id,KoshPlan.seller_id==seller_id))
    if line is None:raise LookupError("PLAN_LINE_NOT_FOUND")
    plan=db.get(KoshPlan,line.plan_id)
    if plan.status!="VALID" or line.status!="VALID":raise ValueError("VALID_PLAN_REQUIRED")
    target=Decimal(plan.planning_details["target_probability"])
    alert_week=plan.planning_details["alert_week"]
    if Decimal(str(plan.after_probabilities[alert_week-1]))>target or any(Decimal(str(p))>=Decimal(plan.planning_details["alert_threshold"]) for p in plan.after_probabilities):raise ValueError("PLAN_PROOF_INVALID")
    latest=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()).limit(1))
    if not latest or latest.id!=plan.forecast_run_id or latest.input_fingerprint!=plan.forecast_fingerprint:raise ValueError("STALE_PLAN")
    from app.finance.forecast import current_fingerprint
    if current_fingerprint(db,latest)!=latest.input_fingerprint:raise ValueError("STALE_PLAN_INPUTS")
    action=PRODUCT_ACTIONS.get(line.product_id)
    if action is None:raise ValueError("UNSUPPORTED_PLAN_PRODUCT")
    existing=db.scalar(select(KoshActionIntent).where(KoshActionIntent.plan_line_id==line.id,KoshActionIntent.action_type==action))
    if existing:
        append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(creator_id),action="intent.propose.repeat",tier=existing.tier,payload={"intent_id":existing.id},policy_decision="ALLOW")
        return existing
    terms=next((e for e in line.evidence if "funding_date" in e),None)
    if terms is None:raise ValueError("PLAN_DATES_REQUIRED")
    params={"amount_paise":line.amount_paise,"product_code":line.product_id,"funding_date":terms["funding_date"],"repayment_date":terms.get("repayment_date"),"days":terms["days"],"cost_paise":line.cost_paise,"effective_annual_rate":line.effective_annual_rate,"params_origin":"PLANNER","forecast_fingerprint":plan.forecast_fingerprint}
    if line.scope_ids:
        if len(line.scope_ids)!=1:raise ValueError("SINGLE_INVOICE_SCOPE_REQUIRED")
        invoice=db.scalar(select(KoshInvoice).where(KoshInvoice.id==line.scope_ids[0],KoshInvoice.seller_id==seller_id,KoshInvoice.status=="OPEN"))
        if invoice is None:raise ValueError("VERIFIED_INVOICE_REQUIRED")
        if line.amount_paise>invoice.amount_paise-(invoice.paid_amount_paise or 0):raise ValueError("INVOICE_CAP_EXCEEDED")
        params.update(invoice_id=invoice.id,counterparty_id=invoice.counterparty_id)
    if TIERS[action]=="T2":params["allowlist_key"]=f"counterparty:{params['counterparty_id']}"
    else:
        params.update(allowlist_key=f"recipient:{line.product_id}",recipient_id=line.product_id,sharing_purpose=action,sharing_fields=["invoice_id","amount_paise","due_date"] if action=="TREDS_FINANCE" else ["amount_paise"] if action=="OD_DRAWDOWN" else ["gstin","udyam_number","last_fy_turnover_paise","incorporation_date"])
    row=KoshActionIntent(id=str(uuid.uuid4()),seller_id=seller_id,source=source,action_type=action,params=params,plan_line_id=line.id,tier=TIERS[action],params_hash="",status="PROPOSED",created_by_user_id=creator_id,policy_decision={})
    row.params_hash=current_hash(row)
    decision=decision_for(db,row);row.policy_decision=decision.as_dict()
    if decision.decision=="DENY":row.status="BLOCKED"
    db.add(row);db.flush()
    append_event(db,seller_id=seller_id,actor_type="SYSTEM",actor_id=str(creator_id),action="security.intent_blocked" if row.status=="BLOCKED" else "intent.propose",tier=decision.tier,payload={"intent_id":row.id,"plan_line_id":line.id,"params_hash":row.params_hash,"source":source,"policy":decision.as_dict()},policy_decision=decision.decision)
    return row
