"""Deterministic thirteen-week cash forecast using integer-paise inputs."""
from __future__ import annotations
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib, json, random
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.kosh_models import KoshBankTransaction,KoshCounterparty,KoshInvoice,KoshObligation
from app.database.models import SellerAttribute,SellerRevision

def week_bounds(as_of:date,index:int=1)->tuple[date,date]:
    start=as_of-timedelta(days=as_of.weekday())+timedelta(weeks=index-1);return start,start+timedelta(days=6)

def _paise(values:list[int],fraction:str)->int:
    if not values:return 0
    ordered=sorted(values);position=Decimal(len(ordered)-1)*Decimal(fraction);lower=int(position);upper=min(lower+1,len(ordered)-1)
    value=Decimal(ordered[lower])+Decimal(ordered[upper]-ordered[lower])*(position-lower)
    return int(value.quantize(Decimal("1"),rounding=ROUND_HALF_UP))

def _next_workday(value:date)->date:
    while value.weekday()>=5:value+=timedelta(days=1)
    return value

def obligation_dates(row:KoshObligation,start:date,end:date)->list[date]:
    if not row.active:return []
    if row.recurrence=="ONE_OFF":return [row.next_due_date] if start<=row.next_due_date<=end else []
    result=[];cursor=date(start.year,start.month,1)
    while cursor<=end:
        if row.kind=="PAYROLL":
            due=date(cursor.year,cursor.month,monthrange(cursor.year,cursor.month)[1])
            while due.weekday()>=5:due-=timedelta(days=1)
        else:due=_next_workday(date(cursor.year,cursor.month,min(row.day_of_month or row.next_due_date.day,monthrange(cursor.year,cursor.month)[1])))
        if start<=due<=end:result.append(due)
        cursor=(cursor.replace(day=28)+timedelta(days=4)).replace(day=1)
    return result

@dataclass(frozen=True)
class ForecastInputs:
    opening_balance_paise:int
    invoices:tuple[dict[str,object],...]
    obligations:tuple[dict[str,object],...]
    portfolio_delays:tuple[int,...]
    customer_delays:dict[int,tuple[int,...]]
    historical_sales:tuple[int,...]
    historical_purchases:tuple[int,...]
    under_review_paise:int

def load_inputs(db:Session,seller_id:int,as_of:date)->ForecastInputs:
    bank=db.scalar(select(KoshBankTransaction).where(KoshBankTransaction.seller_id==seller_id,KoshBankTransaction.txn_date<=as_of).order_by(KoshBankTransaction.txn_date.desc(),KoshBankTransaction.id.desc()).limit(1))
    rows=db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id,KoshInvoice.invoice_date<=as_of)).all()
    cutoff=as_of-timedelta(days=730);portfolio=[];customer={};open_rows=[];review=0;sales=[0]*26;purchases=[0]*26;history_start=as_of-timedelta(weeks=26)
    for invoice,party in rows:
        paid_by_as_of=bool(invoice.paid_date and invoice.paid_date<=as_of)
        remaining=max(0,invoice.amount_paise-((invoice.paid_amount_paise or 0) if paid_by_as_of else 0))
        if invoice.status=="REVIEW":review+=remaining;continue
        if invoice.status=="PAID" and paid_by_as_of and invoice.due_date>=cutoff:
            delay=max(0,(invoice.paid_date-invoice.due_date).days);weight=2 if invoice.paid_date>=as_of-timedelta(days=90) else 1
            portfolio.extend([delay]*weight);customer.setdefault(invoice.counterparty_id,[]).extend([delay]*weight)
        if not paid_by_as_of and remaining:open_rows.append({"id":invoice.id,"counterparty_id":invoice.counterparty_id,"party":party.name,"number":invoice.invoice_number,"direction":invoice.direction,"due_date":invoice.due_date,"amount_paise":remaining})
        if history_start<=invoice.invoice_date<=as_of:
            idx=min(25,max(0,(invoice.invoice_date-history_start).days//7));(sales if invoice.direction=="RECEIVABLE" else purchases)[idx]+=invoice.amount_paise
    start=week_bounds(as_of)[0];end=week_bounds(as_of,13)[1]
    obligations=tuple({"id":row.id,"kind":row.kind,"label":row.label,"amount_paise":row.amount_paise,"dates":[d.isoformat() for d in obligation_dates(row,start,end)]} for row in db.scalars(select(KoshObligation).where(KoshObligation.seller_id==seller_id,KoshObligation.active.is_(True))))
    return ForecastInputs(bank.balance_paise if bank else 0,tuple(open_rows),obligations,tuple(portfolio or [30,45,60]),{key:tuple(value) for key,value in customer.items()},tuple(sales),tuple(purchases),review)

def buffer_for_seller(db:Session,seller_id:int,default:int=100_000_000)->int:
    row=db.scalar(select(SellerAttribute).join(SellerRevision,SellerRevision.id==SellerAttribute.revision_id).where(SellerRevision.seller_id==seller_id,SellerRevision.is_active.is_(True),SellerAttribute.key=="cash_buffer_paise").order_by(SellerRevision.revision_number.desc()).limit(1))
    return int(row.value_number) if row and row.value_number is not None else default

def fingerprint(inputs:ForecastInputs,params:dict[str,object])->str:
    payload={"opening":inputs.opening_balance_paise,"invoices":inputs.invoices,"obligations":inputs.obligations,"portfolio":inputs.portfolio_delays,"customer":inputs.customer_delays,"sales":inputs.historical_sales,"purchases":inputs.historical_purchases,"review":inputs.under_review_paise,"params":params}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def sample_delay(rng:random.Random,inputs:ForecastInputs,invoice:dict[str,object],as_of:date,shift:int=0)->int:
    observations=list(inputs.customer_delays.get(int(invoice["counterparty_id"]),()))
    if len(observations)<5:observations+=list(inputs.portfolio_delays)[:max(1,5-len(observations))]
    overdue=max(0,(as_of-invoice["due_date"]).days);conditional=[value for value in observations if value>overdue]
    if overdue and not conditional:
        p75=sorted(inputs.portfolio_delays)[int((len(inputs.portfolio_delays)-1)*.75)];return max(overdue,overdue+max(7,p75-overdue)+shift)
    return max(0,rng.choice(conditional or observations or [30])+shift)

def simulate(inputs:ForecastInputs,*,as_of:date,n_paths:int=2000,seed:int=42,include_forecast_sales:bool=True,buffer_paise:int=100_000_000,customer_delay_shift_days:dict[int,int]|None=None,exclude_counterparties:set[int]|None=None,extra_inflows:list[dict[str,object]]|None=None)->dict[str,object]:
    shifts=customer_delay_shift_days or {};excluded=exclude_counterparties or set();extras=extra_inflows or [];starts=[week_bounds(as_of,index)[0] for index in range(1,14)]
    balances=[[] for _ in range(13)];totals=[[0]*13 for _ in range(4)]
    for path_index in range(n_paths):
        rng=random.Random(seed*1_000_003+path_index);events=[[] for _ in range(13)]
        for invoice in inputs.invoices:
            if int(invoice["counterparty_id"]) in excluded:continue
            pay_date=invoice["due_date"] if invoice["direction"]=="PAYABLE" else invoice["due_date"]+timedelta(days=sample_delay(rng,inputs,invoice,as_of,shifts.get(int(invoice["counterparty_id"]),0)))
            idx=(pay_date-starts[0]).days//7
            if 0<=idx<13:events[idx].append((int(invoice["amount_paise"])*(1 if invoice["direction"]=="RECEIVABLE" else -1),"committed"))
        for obligation in inputs.obligations:
            for raw in obligation["dates"]:
                idx=(date.fromisoformat(raw)-starts[0]).days//7
                if 0<=idx<13:events[idx].append((-int(obligation["amount_paise"]),"committed"))
        for extra in extras:
            idx=(date.fromisoformat(str(extra["date"]))-starts[0]).days//7
            if 0<=idx<13:events[idx].append((int(extra["amount_paise"]),"committed"))
        if include_forecast_sales:
            for issued_idx in range(13):
                sale_idx=issued_idx+6+max(0,rng.choice(inputs.portfolio_delays or (0,)))//7
                purchase_idx=issued_idx+5
                if sale_idx<13:events[sale_idx].append((rng.choice(inputs.historical_sales or (0,)),"forecast"))
                if purchase_idx<13:events[purchase_idx].append((-rng.choice(inputs.historical_purchases or (0,)),"forecast"))
        balance=inputs.opening_balance_paise
        for idx,week_events in enumerate(events):
            for amount,component in week_events:
                balance+=amount
                totals[0 if amount>=0 and component=="committed" else 1 if amount>=0 else 2 if component=="committed" else 3][idx]+=abs(amount)
            balances[idx].append(balance)
    weeks=[]
    for idx,values in enumerate(balances):
        shortfalls=[max(0,buffer_paise-value) for value in values]
        expected=[int((Decimal(row[idx])/n_paths).quantize(Decimal("1"),rounding=ROUND_HALF_UP)) for row in totals]
        weeks.append({"week_index":idx+1,"week_start":starts[idx],"week_end":starts[idx]+timedelta(days=6),"p10_closing_balance_paise":_paise(values,".10"),"p50_closing_balance_paise":_paise(values,".50"),"p90_closing_balance_paise":_paise(values,".90"),"expected_inflow_committed_paise":expected[0],"expected_inflow_forecast_paise":expected[1],"expected_outflow_committed_paise":expected[2],"expected_outflow_forecast_paise":expected[3],"prob_below_buffer":sum(value<buffer_paise for value in values)/n_paths,"expected_shortfall_paise":int((Decimal(sum(shortfalls))/n_paths).quantize(Decimal("1"),rounding=ROUND_HALF_UP))})
    return {"as_of_date":as_of,"horizon_weeks":13,"n_paths":n_paths,"seed":seed,"buffer_paise":buffer_paise,"under_review_paise":inputs.under_review_paise,"weeks":weeks}
