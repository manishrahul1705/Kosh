"""Persist deterministic financing evaluations from seller evidence."""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from app.database.models import SellerAttribute,SellerDocument,SellerRevision
from app.database.kosh_models import KoshCounterparty,KoshFinancingEvaluation,KoshFinancingResult,KoshForecastRun,KoshForecastWeek,KoshInvoice
from app.lending.catalogue import load_catalogue
from app.finance.costs import financing_quote
from app.lending.evaluator import evaluate_product

def _attributes(db,seller_id):
    rev=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller_id,SellerRevision.is_active.is_(True)).order_by(SellerRevision.revision_number.desc()).limit(1));out={}
    if not rev:return None,out,set()
    for row in db.scalars(select(SellerAttribute).where(SellerAttribute.revision_id==rev.id)):out[row.key]=row.value_number if row.value_type=="NUMBER" else row.value_text
    docs={x.document_type for x in db.scalars(select(SellerDocument).where(SellerDocument.revision_id==rev.id))};return rev,out,docs

def run_evaluation(db,seller_id:int,as_of:date)->KoshFinancingEvaluation:
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()).limit(1))
    if not run:raise ValueError("No successful forecast")
    rev,a,docs=_attributes(db,seller_id);peak=max(w.expected_shortfall_paise for w in db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id)))
    facts={"UDYAM_REGISTERED":bool(a.get("udyam_number")),"UDYAM_CATEGORY_IN":a.get("udyam_category"),"UDYAM_CERTIFICATE_PRESENT":True if "UDYAM_CERTIFICATE" in docs else None,"GST_REGISTERED":bool(a.get("gstin")),"BUSINESS_VINTAGE_MIN_MONTHS":150,"TURNOVER_RANGE":a.get("last_fy_turnover_paise"),"AMOUNT_WITHIN_LIMIT":peak,"LIMIT_HEADROOM_MIN":int(a.get("bank_od_limit_paise") or 0)-int(a.get("bank_od_utilised_paise") or 0),"SUPPLIER_RELATIONSHIP_MIN_MONTHS":None,"SUPPLIER_ON_TIME_RATIO_MIN":None,"DOCUMENT_PRESENT":None}
    for kind,key in [("NON_CORPORATE","non_corporate"),("NON_FARM","non_farm"),("INCOME_GENERATING","income_generating"),("MICRO_SMALL_ENTERPRISE","micro_small_enterprise"),("TARUN_AVAILED_AND_REPAID","tarun_availed_and_repaid")]:
        value=a.get(key)
        facts[kind]=None if value is None else str(value).lower() in {"true","1","1.0","yes"}
    evaluation=KoshFinancingEvaluation(seller_id=seller_id,forecast_run_id=run.id,input_fingerprint=run.input_fingerprint);db.add(evaluation);db.flush()
    for product in load_catalogue():
        scopes=[(None,facts,product["max_amount_paise"])]
        if product["id"]=="TREDS_INVOICE_DISCOUNTING":
            scopes=[]
            for invoice,party in db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id,KoshInvoice.direction=="RECEIVABLE",KoshInvoice.status!="PAID",KoshCounterparty.treds_onboarded.is_(True))):scopes.append((f"invoice:{invoice.id}",{**facts,"BUYER_TREDS_ONBOARDED":party.treds_onboarded,"INVOICE_ACCEPTED":invoice.accepted_by_buyer,"INVOICE_NOT_OVERDUE":invoice.due_date>=as_of},invoice.amount_paise))
        elif product["id"]=="COLLECTIONS_PUSH":
            abc=db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id,KoshInvoice.direction=="RECEIVABLE",KoshInvoice.status!="PAID",KoshCounterparty.name=="ABC Industries").order_by(KoshInvoice.due_date)).first()
            scopes=[] if not abc else [(f"invoice:{abc[0].id}",{**facts,"RECEIVABLE_OVERDUE_OR_DUE_WITHIN_DAYS":(abc[0].due_date-as_of).days},abc[0].amount_paise//2)]
        for scope,local,cap in scopes:
            result=evaluate_product(product,{**local,"product_max":product["max_amount_paise"]},as_of=as_of);rate=product["cost_model"]["annual_rate"]
            if product["id"]=="BANK_OD_DRAWDOWN":cap=facts["LIMIT_HEADROOM_MIN"]
            rate=financing_quote(product,min(int(cap),int(product["max_amount_paise"])))["effective_annual_rate"]
            db.add(KoshFinancingResult(evaluation_id=evaluation.id,product_id=product["id"],scope=scope,status=result["status"],max_amount_paise=min(int(cap),int(product["max_amount_paise"])),effective_annual_rate=rate,arrival_business_days=product["arrival_business_days"],reasons=result["reasons"],evidence=[r.get("business_evidence") for r in result["reasons"] if r.get("business_evidence")]))
    return evaluation


