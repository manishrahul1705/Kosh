"""Read-only computed facts; no intent or messaging imports."""
import re,json
from decimal import Decimal
from sqlalchemy import select
from app.database.kosh_models import KoshForecastRun,KoshForecastWeek,KoshPlan,KoshFinancingResult,KoshFinancingEvaluation,KoshInvoice
from app.ai.providers.base import AIRequest
from app.ai.providers.mock import MockProvider
GUARD=re.compile(r"ignore\s+(?:all|previous)\s+instructions|\bsystem\s*:|pay\s+(?:supplier|vendor)|\b(?:transfer|send|approve|execute)\b|change.{0,40}bank",re.I)

def computed_facts(db,seller_id):
    facts=[]
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()))
    if run:
        week=db.scalar(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id).order_by(KoshForecastWeek.prob_below_buffer.desc(),KoshForecastWeek.week_index))
        if week:facts.append({"id":f"forecast:{run.id}:week:{week.week_index}","text":f"Forecast run {run.id}, week {week.week_index}: {Decimal(str(week.prob_below_buffer))*100}% probability below buffer; P50 closing INR {Decimal(week.p50_closing_balance_paise)/100:,.2f}.","href":"/cash"})
    plan=db.scalar(select(KoshPlan).where(KoshPlan.seller_id==seller_id).order_by(KoshPlan.id.desc()))
    if plan:facts.append({"id":f"plan:{plan.id}","text":f"Plan {plan.id} is {plan.status}; computed total cost INR {Decimal(plan.total_cost_paise)/100:,.2f}.","href":"/plan"})
    for row in db.scalars(select(KoshFinancingResult).join(KoshFinancingEvaluation,KoshFinancingEvaluation.id==KoshFinancingResult.evaluation_id).where(KoshFinancingEvaluation.seller_id==seller_id).order_by(KoshFinancingResult.id.desc()).limit(4)):
        facts.append({"id":f"option:{row.id}","text":f"Option record {row.id}: {row.product_id}, {row.status}.","href":"/plan"})
    for row in db.scalars(select(KoshInvoice).where(KoshInvoice.seller_id==seller_id,KoshInvoice.status=="OPEN").order_by(KoshInvoice.id).limit(2)):
        facts.append({"id":f"invoice:{row.id}","text":f"Invoice record {row.id}: outstanding INR {Decimal(max(0,row.amount_paise-(row.paid_amount_paise or 0)))/100:,.2f}.","href":"/ledger"})
    return facts

def answer(db,seller_id,question,*,provider=None):
    if GUARD.search(question):return {"status":"REFUSED","reason":"Read-only cash chat cannot create intents, approve actions, send messages or move money.","facts":[],"rule_ids":["CHAT_READ_ONLY","INJECTION_GUARD"]}
    facts=computed_facts(db,seller_id)
    if provider is not None:
        if not isinstance(provider,MockProvider):raise ValueError("Only an offline mock is accepted in this build")
        response=provider.generate(AIRequest(system="Select fact_ids only from the supplied computed records. No action tools. Do not return prose.",user=json.dumps({"facts":facts}),max_output_tokens=300))
        try:ids=json.loads(response.text).get('fact_ids',[])
        except (ValueError,AttributeError):ids=[]
        selected=[fact for fact in facts if fact['id'] in ids]
        if selected:facts=selected
    return {"status":"READ_ONLY","reason":"Offline computed facts; every number is linked to its record. No document instructions are included.","facts":facts,"rule_ids":["COMPUTED_FACTS_ONLY"]}
