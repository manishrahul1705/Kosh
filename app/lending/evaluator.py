"""Deterministic financing criterion evaluation."""
from __future__ import annotations
from datetime import date
from decimal import Decimal

PASS="MATCHED";FAIL="NOT_MATCHED";REVIEW="REVIEW_REQUIRED"

def criterion_result(criterion:dict, facts:dict, *, as_of:date)->dict:
    kind=criterion.get("type");source=criterion.get("source") or {};base={"criterion":kind,"product_clause":source,"business_evidence":None}
    if source.get("as_of_date") and (as_of-date.fromisoformat(source["as_of_date"])).days>180:return {**base,"status":REVIEW,"reason_code":"STALE_SOURCE","reason":"Source is older than 180 days; verify before relying."}
    known={"UDYAM_REGISTERED","UDYAM_CATEGORY_IN","UDYAM_CERTIFICATE_PRESENT","GST_REGISTERED","BUSINESS_VINTAGE_MIN_MONTHS","TURNOVER_RANGE","AMOUNT_WITHIN_LIMIT","LIMIT_HEADROOM_MIN","BUYER_TREDS_ONBOARDED","INVOICE_ACCEPTED","INVOICE_NOT_OVERDUE","RECEIVABLE_OVERDUE_OR_DUE_WITHIN_DAYS","SUPPLIER_RELATIONSHIP_MIN_MONTHS","SUPPLIER_ON_TIME_RATIO_MIN","DOCUMENT_PRESENT"}
    if kind not in known:return {**base,"status":REVIEW,"reason_code":"UNKNOWN_CRITERION","reason":"Criterion is not supported."}
    value=facts.get(kind)
    if value is None:return {**base,"status":REVIEW,"reason_code":"MISSING_DATA","reason":"Required business evidence is missing."}
    expected=criterion.get("value",True)
    if kind.endswith("_IN"):ok=value in criterion.get("values",[])
    elif kind.endswith("_MIN_MONTHS") or kind.endswith("_MIN"):ok=Decimal(str(value))>=Decimal(str(expected))
    elif kind=="TURNOVER_RANGE":ok=criterion.get("min",0)<=value<=criterion.get("max",10**30)
    elif kind=="AMOUNT_WITHIN_LIMIT":ok=value<=criterion.get("max",facts.get("product_max",0))
    elif kind=="RECEIVABLE_OVERDUE_OR_DUE_WITHIN_DAYS":ok=value<=criterion.get("days",30)
    else:ok=bool(value)==bool(expected)
    return {**base,"business_evidence":{"value":value,"source":facts.get(kind+"_SOURCE")},"status":PASS if ok else FAIL,"reason_code":"CRITERION_MET" if ok else "CRITERION_FAILED","reason":"Criterion met." if ok else "Business evidence does not meet this criterion."}

def evaluate_product(product:dict,facts:dict,*,as_of:date)->dict:
    results=[criterion_result(c,facts,as_of=as_of) for c in product.get("criteria",[])]
    if product["id"]=="GEM_SAHAY_PO_FINANCE":results.append({"criterion":"PRODUCT_STATUS","product_clause":"assumption","business_evidence":None,"status":REVIEW,"reason_code":"PRODUCT_UNDER_REVISION","reason":"repayment routing issues reported by lenders; product under revision"})
    status=FAIL if any(r["status"]==FAIL for r in results) else REVIEW if any(r["status"]==REVIEW for r in results) else PASS
    return {"product_id":product["id"],"status":status,"reasons":results}
