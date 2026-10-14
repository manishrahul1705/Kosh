"""Deterministic reminder data and statutory monthly-rest arithmetic."""
from calendar import monthrange
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from app.core.config import get_settings

def monthly_rest(day,offset):
    absolute=day.year*12+day.month-1+offset;year,month=divmod(absolute,12);month+=1
    return date(year,month,min(day.day,monthrange(year,month)[1]))

def msmed_interest(principal_paise,acceptance_date,as_of,*,agreement_status="UNKNOWN",agreed_days=None,supplier_mse=None,bank_rate=None):
    annual=Decimal(bank_rate if bank_rate is not None else get_settings().kosh_rbi_bank_rate)*3/100
    base={"annual_rate":str(annual),"basis":"Section 16: three times configured RBI bank rate, monthly rests; actual/365 stub days.","interest_paise":None}
    if acceptance_date is None or agreement_status not in {"NONE","AGREED"} or supplier_mse is None or (agreement_status=="AGREED" and (agreed_days is None or agreed_days<0)):
        return {**base,"status":"REVIEW_REQUIRED","reason":"Acceptance date, agreement and MSE applicability require evidence."}
    if supplier_mse is False:return {**base,"status":"NOT_APPLICABLE","reason":"Documented supplier is not a micro/small enterprise."}
    period=15 if agreement_status=="NONE" else min(agreed_days,45)
    due=acceptance_date+timedelta(days=period)
    balance=Decimal(principal_paise);cursor=due;months=0
    while monthly_rest(due,months+1)<=as_of:
        months+=1;cursor=monthly_rest(due,months);balance*=1+annual/12
    stub=max(0,(as_of-cursor).days);balance*=1+annual*Decimal(stub)/365
    interest=int((balance-Decimal(principal_paise)).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    return {**base,"status":"COMPUTED","interest_paise":max(0,interest),"due_date":due.isoformat(),"overdue_days":max(0,(as_of-due).days),"monthly_rests":months,"stub_days":stub,"payment_period_days":period,"reason":"Documented terms; Section 15 caps agreed credit at 45 days, or 15 days when none agreed."}

def reminder(invoice,party,*,tone="PROFESSIONAL"):
    amount=max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0))
    lead={"GENTLE":"A friendly reminder", "PROFESSIONAL":"Payment reminder", "FIRM":"Overdue payment follow-up"}[tone]
    return f"{lead}: {party.name}, please arrange INR {Decimal(amount)/100:,.2f} against invoice {invoice.invoice_number}, due {invoice.due_date.isoformat()}. Please confirm the payment date."
