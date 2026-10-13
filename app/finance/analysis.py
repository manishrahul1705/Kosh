"""Evidence-backed business cash-cycle metrics."""
from __future__ import annotations
from collections import defaultdict
from datetime import date,timedelta
from statistics import median
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.kosh_models import KoshCounterparty,KoshInvoice

def business_analysis(db:Session,seller_id:int,as_of:date)->dict[str,object]:
    rows=db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id,KoshInvoice.invoice_date<=as_of,KoshInvoice.status!="REVIEW")).all()
    settled=[(i,p) for i,p in rows if i.status=="PAID" and i.paid_date and i.paid_date<=as_of];sales=[(i,p) for i,p in rows if i.direction=="RECEIVABLE"];purchases=[(i,p) for i,p in rows if i.direction=="PAYABLE"]
    def days(items):return [max(0,((i.paid_date or as_of)-i.invoice_date).days) for i,_ in items]
    dso=median(days([(i,p) for i,p in settled if i.direction=="RECEIVABLE"])) if settled else 0;dpo=median(days([(i,p) for i,p in settled if i.direction=="PAYABLE"])) if settled else 0
    customer_totals=defaultdict(int)
    for i,p in sales:customer_totals[p.name]+=i.amount_paise
    total=sum(customer_totals.values()) or 1;shares=sorted((value/total for value in customer_totals.values()),reverse=True)
    ageing={"0_30":0,"31_60":0,"61_90":0,"90_plus":0}
    for i,_ in sales:
        if i.status=="PAID":continue
        age=max(0,(as_of-i.due_date).days);key="0_30" if age<=30 else "31_60" if age<=60 else "61_90" if age<=90 else "90_plus";ageing[key]+=max(0,i.amount_paise-(i.paid_amount_paise or 0))
    customers=[]
    for name in customer_totals:
        items=[i for i,p in settled if p.name==name and i.direction=="RECEIVABLE"];delays=[(i.paid_date-i.due_date).days for i in items]
        recent=[d for i,d in zip(items,delays) if i.paid_date>=as_of-timedelta(days=90)];older=[d for i,d in zip(items,delays) if as_of-timedelta(days=180)<=i.paid_date<as_of-timedelta(days=90)]
        customers.append({"customer":name,"on_time_percent":sum(d<=0 for d in delays)/len(delays) if delays else 0,"median_delay_days":median(delays) if delays else 0,"trend_90_days":(median(recent)-median(older)) if recent and older else 0,"evidence_invoice_ids":[i.id for i in items]})
    return {"as_of_date":as_of,"dso_days":dso,"dpo_days":dpo,"cash_conversion_cycle_days":dso-dpo,"top_3_customer_share":sum(shares[:3]),"customer_hhi":sum(value*value for value in shares),"overdue_ageing_paise":ageing,"customers":customers,"evidence_invoice_ids":[i.id for i,_ in rows]}
