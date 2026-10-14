"""One-page source-grounded cash snapshot; generated locally."""
from io import BytesIO
from decimal import Decimal
from collections import defaultdict
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4
from sqlalchemy import select
from app.database.models import Seller
from app.database.kosh_models import KoshForecastRun,KoshForecastWeek,KoshPlan,KoshPlanLine,KoshFinancingEvaluation,KoshFinancingResult,KoshAuditEntry
from app.lending.catalogue import load_catalogue

def snapshot(db,seller_id):
    seller=db.get(Seller,seller_id)
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()))
    if run is None:raise ValueError("Successful forecast required")
    weeks=list(db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id).order_by(KoshForecastWeek.week_index)))
    if len(weeks)!=13:raise ValueError("Complete thirteen-week forecast required")
    plan=db.scalar(select(KoshPlan).where(KoshPlan.seller_id==seller_id).order_by(KoshPlan.id.desc()))
    lines=list(db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id==plan.id))) if plan else []
    evaluation=db.scalar(select(KoshFinancingEvaluation).where(KoshFinancingEvaluation.seller_id==seller_id).order_by(KoshFinancingEvaluation.id.desc()))
    results=list(db.scalars(select(KoshFinancingResult).where(KoshFinancingResult.evaluation_id==evaluation.id))) if evaluation else []
    options=[]
    for product in load_catalogue():
        rows=[r for r in results if r.product_id==product['id']]
        status='MATCHED' if any(r.status=='MATCHED' for r in rows) else 'REVIEW_REQUIRED' if any(r.status=='REVIEW_REQUIRED' for r in rows) else 'NOT_MATCHED' if rows else 'NOT_EVALUATED'
        clause=next((c for c in product.get('criteria',[]) if c.get('source_url') or c.get('source',{}).get('url')),None)
        source=(clause.get('source_url') or clause.get('source',{}).get('url')) if clause else 'Catalogue illustrative terms'
        if clause and clause.get('source',{}).get('verified') is not True:source+=' (unverified)'
        options.append({'product':product['id'],'status':status,'rate':next((r.effective_annual_rate for r in rows if r.effective_annual_rate is not None),None),'source':source})
    head=db.scalar(select(KoshAuditEntry).order_by(KoshAuditEntry.sequence.desc()).limit(1))
    return {'seller':seller.name,'seller_id':seller_id,'run_id':run.id,'as_of':run.as_of_date.isoformat(),'buffer_paise':run.buffer_paise,'weeks':[{'week':w.week_index,'p10':w.p10_closing_balance_paise,'p50':w.p50_closing_balance_paise,'p90':w.p90_closing_balance_paise,'risk':str(w.prob_below_buffer)} for w in weeks],'plan_id':plan.id if plan else None,'plan_status':plan.status if plan else 'NONE','plan_stale':bool(plan and plan.forecast_run_id!=run.id and plan.planning_details.get('actual_execution',{}).get('forecast_run_id')!=run.id),'plan_cost_paise':plan.total_cost_paise if plan else None,'lines':[{'product':l.product_id,'amount':l.amount_paise,'cost':l.cost_paise,'days':next((e['days'] for e in l.evidence if 'days' in e),0)} for l in lines],'options':options,'evaluation_id':evaluation.id if evaluation else None,'audit_hash':head.entry_hash if head else 'No audit entries','audit_sequence':head.sequence if head else 0}

def build_pdf(data):
    stream=BytesIO();canvas=Canvas(stream,pagesize=A4,invariant=1);width,height=A4
    def text(y,value,size=9):
        canvas.setFont('Helvetica',size);canvas.drawString(38,y,str(value).encode('ascii','replace').decode()[:115])
    def inr(value):return f"{Decimal(value)/100:,.2f}"
    canvas.setFillColorRGB(.08,.17,.32);canvas.rect(0,height-80,width,80,fill=1,stroke=0);canvas.setFillColorRGB(1,1,1)
    text(height-32,'KOSH | CASH POSITION',18);text(height-51,data['seller'],11);text(height-67,f"As of {data['as_of']} | seller {data['seller_id']} | forecast run {data['run_id']}",9)
    canvas.setFillColorRGB(0,0,0);y=height-101
    text(y,f"Buffer INR {inr(data['buffer_paise'])}. Forecast estimates, not guaranteed receipts.")
    y-=22;text(y,'Week       P10 (INR)            P50 (INR)            P90 (INR)            Below buffer',9);y-=15
    for week in data['weeks']:
        text(y,f"{week['week']:>2}          {inr(week['p10']):>14}         {inr(week['p50']):>14}         {inr(week['p90']):>14}         {Decimal(week['risk'])*100:.2f}%",8);y-=13
    peak=max(data['weeks'],key=lambda w:Decimal(w['risk']));y-=10;text(y,f"Highest risk: week {peak['week']}, {Decimal(peak['risk'])*100:.2f}% below buffer. Source: /cash run {data['run_id']}.");y-=24
    text(y,f"Plan {data['plan_id'] or 'none'}: {data['plan_status']}{' (stale basis; rebuild)' if data['plan_stale'] else ''} | cost INR {inr(data['plan_cost_paise']) if data['plan_cost_paise'] is not None else 'unknown'}",11);y-=17
    groups=defaultdict(lambda:[0,0,0])
    for line in data['lines']:
        groups[line['product']][0]+=1;groups[line['product']][1]+=line['amount'];groups[line['product']][2]+=line['cost']
    for product,(count,amount,cost) in list(groups.items())[:6]:text(y,f"{product} ({count} line(s)): amount INR {inr(amount)}, cost INR {inr(cost)}",8);y-=13
    y-=12;text(y,f"Options (90-day quote basis) and evidence | evaluation {data['evaluation_id'] or 'unknown'} | full criteria: /plan",11);y-=16
    for option in data['options']:
        rate=f"{Decimal(option['rate'])*100:.2f}%" if option['rate'] is not None else 'unknown'
        text(y,f"{option['product']}: {option['status']}; effective annual quote {rate}",8);y-=11
        text(y,f"  Evidence: {option['source']}",7);y-=13
    y-=7;text(y,f"Audit snapshot sequence {data['audit_sequence']} (before generation audit)",8);y-=12
    text(y,data['audit_hash'],7);y-=16
    text(y,'Internal application-pack draft. External sharing requires scoped consent, approval and OTP.',8)
    canvas.showPage();canvas.save();return stream.getvalue()
