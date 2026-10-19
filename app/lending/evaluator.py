"""Deterministic financing criterion evaluation."""
from __future__ import annotations
from datetime import date
from decimal import Decimal

PASS="MATCHED";FAIL="NOT_MATCHED";REVIEW="REVIEW_REQUIRED"

def criterion_result(criterion:dict, facts:dict, *, as_of:date)->dict:
    kind=criterion.get("type");source=criterion.get("source") or {};base={"criterion":kind,"product_clause":source,"business_evidence":None}
    source_date=source.get("verified_on") or source.get("as_of_date") or criterion.get("verified_on")
    if source_date:
        try:age=(as_of-date.fromisoformat(source_date)).days
        except (ValueError,TypeError):age=-1
        if age<0:return {**base,"status":REVIEW,"reason_code":"INVALID_SOURCE_DATE","reason":"Source date needs verification."}
        if age>180:return {**base,"status":REVIEW,"reason_code":"STALE_SOURCE","reason":"Source is older than 180 days; verify before relying."}
    known={"UDYAM_REGISTERED","UDYAM_CATEGORY_IN","UDYAM_CERTIFICATE_PRESENT","GST_REGISTERED","BUSINESS_VINTAGE_MIN_MONTHS","TURNOVER_RANGE","AMOUNT_WITHIN_LIMIT","LIMIT_HEADROOM_MIN","BUYER_TREDS_ONBOARDED","INVOICE_ACCEPTED","INVOICE_NOT_OVERDUE","RECEIVABLE_OVERDUE_OR_DUE_WITHIN_DAYS","SUPPLIER_RELATIONSHIP_MIN_MONTHS","SUPPLIER_ON_TIME_RATIO_MIN","SUPPLIER_AGREEMENT_CONFIRMED","DOCUMENT_PRESENT","COLLECTION_REPEAT_OUTCOME_PRESENT","INVOICE_EVIDENCE_VERIFIED","INVOICE_OPEN_AMOUNT_POSITIVE","INVOICE_DUE_AFTER_FUNDING","MUDRA_CATEGORY_AMOUNT","NON_CORPORATE","NON_FARM","INCOME_GENERATING","MICRO_SMALL_ENTERPRISE","TARUN_AVAILED_AND_REPAID"}
    if kind not in known:return {**base,"status":REVIEW,"reason_code":"UNKNOWN_CRITERION","reason":"Criterion is not supported."}
    if kind=="TARUN_AVAILED_AND_REPAID" and facts.get("AMOUNT_WITHIN_LIMIT") is not None and facts["AMOUNT_WITHIN_LIMIT"]<=100_000_000:
        return {**base,"status":PASS,"reason_code":"NOT_APPLICABLE","reason":"Tarun repayment evidence is required only for Tarun Plus (above 10 lakh rupees)."}
    if kind=="COLLECTION_REPEAT_OUTCOME_PRESENT" and facts.get("COLLECTION_REPEAT_ATTEMPT") is False:
        return {**base,"status":PASS,"reason_code":"NOT_APPLICABLE","reason":"No previous successful reminder; repeat-outcome evidence is not applicable."}
    if kind=="SUPPLIER_AGREEMENT_CONFIRMED":
        val=str(facts.get("SUPPLIER_AGREEMENT_CONFIRMED") or "").upper()
        source_info=facts.get("SUPPLIER_AGREEMENT_CONFIRMED_SOURCE")
        if val=="CONFIRMED":
            return {**base,"business_evidence":{"value":"CONFIRMED","source":source_info},"status":PASS,"reason_code":"AGREEMENT_CONFIRMED","reason":"Supplier agreement confirmed by signed addendum."}
        if val=="PROPOSED":
            return {**base,"business_evidence":{"value":"PROPOSED","source":source_info},"status":REVIEW,"reason_code":"PROPOSAL_PENDING_CONFIRMATION","reason":"Supplier extension is proposed; awaiting supplier confirmation. A proposal alone does not change payable due dates."}
        return {**base,"business_evidence":{"value":val or None,"source":source_info} if val else None,"status":REVIEW,"reason_code":"MISSING_DATA","reason":"Supplier agreement confirmation is missing."}
    if kind in {"UDYAM_CERTIFICATE_PRESENT","DOCUMENT_PRESENT"}:
        strength=facts.get(kind+"_STRENGTH")
        if strength is not None:
            val=facts.get(kind)
            source_info=facts.get(kind+"_SOURCE")
            doc_label="Udyam Registration Certificate" if kind=="UDYAM_CERTIFICATE_PRESENT" else "Purchase order document"
            if strength in {"LINKED_DOCUMENT","INDEPENDENTLY_VERIFIED"} and val is True:
                return {**base,"business_evidence":{"value":True,"source":source_info,"strength":strength},"status":PASS,"reason_code":"CRITERION_MET","reason":f"{doc_label} evidence is present ({strength.lower().replace('_', ' ')})."}
            if val is False:
                return {**base,"business_evidence":{"value":False,"source":source_info,"strength":strength},"status":REVIEW,"reason_code":"NEEDS_DOCUMENTATION","reason":f"Needs documentation: {doc_label.lower()} is absent; document must be uploaded or verified rather than entity ineligibility."}
            if strength=="OWNER_DECLARATION":
                return {**base,"business_evidence":{"value":val,"source":source_info,"strength":strength},"status":REVIEW,"reason_code":"NEEDS_DOCUMENTATION","reason":f"Owner declaration alone does not satisfy {doc_label.lower()} requirement; uploaded document or independently verified reference required."}
            return {**base,"business_evidence":{"value":val,"source":source_info,"strength":strength} if val is not None else None,"status":REVIEW,"reason_code":"NEEDS_DOCUMENTATION","reason":f"Needs documentation: {doc_label.lower()} must be uploaded or verified."}
    value=facts.get("AMOUNT_WITHIN_LIMIT" if kind=="MUDRA_CATEGORY_AMOUNT" else kind)
    if value is None:return {**base,"status":REVIEW,"reason_code":"MISSING_DATA","reason":"Required business evidence is missing."}
    expected=criterion.get("value",True)
    if kind=="MUDRA_CATEGORY_AMOUNT":
        lower=criterion["min_exclusive"];upper=criterion["max"]
        ok=0<value<=200_000_000
        return {**base,"business_evidence":{"value":value},"status":PASS if ok else FAIL,"reason_code":"CATEGORY_SELECTED" if lower<value<=upper else "NOT_APPLICABLE" if ok else "ABOVE_PMMY_CAP","reason":f"{criterion['category']}: above {lower} and up to {upper} paise." if ok else "Requested amount is outside the PMMY 20 lakh rupee maximum."}
    if kind.endswith("_IN"):ok=value in criterion.get("values",[])
    elif kind.endswith("_MIN_MONTHS") or kind.endswith("_MIN"):ok=Decimal(str(value))>=Decimal(str(expected))
    elif kind=="TURNOVER_RANGE":ok=criterion.get("min",0)<=value<=criterion.get("max",10**30)
    elif kind=="AMOUNT_WITHIN_LIMIT":ok=value<=criterion.get("max",facts.get("product_max",0))
    elif kind=="RECEIVABLE_OVERDUE_OR_DUE_WITHIN_DAYS":ok=value<=criterion.get("days",30)
    else:ok=bool(value)==bool(expected)
    return {**base,"business_evidence":{"value":value,"source":facts.get(kind+"_SOURCE")},"status":PASS if ok else FAIL,"reason_code":"CRITERION_MET" if ok else "CRITERION_FAILED","reason":"Criterion met." if ok else "Business evidence does not meet this criterion."}

def evaluate_product(product:dict,facts:dict,*,as_of:date)->dict:
    results=[criterion_result(c,facts,as_of=as_of) for c in product.get("criteria",[])]
    if product["id"]=="GEM_SAHAY_PO_FINANCE":results.append({"criterion":"PRODUCT_STATUS","product_clause":"assumption","business_evidence":None,"status":REVIEW,"reason_code":"PRODUCT_UNDER_REVISION","reason":"Required evidence is missing and product terms are not verified against a current primary source."})
    status=FAIL if any(r["status"]==FAIL for r in results) else REVIEW if any(r["status"]==REVIEW for r in results) else PASS
    if product["id"]=="GEM_SAHAY_PO_FINANCE":status=REVIEW
    if product["id"]=="MUDRA_LOAN" and status!=FAIL and any(r["status"]==REVIEW for r in results):status=REVIEW
    return {"product_id":product["id"],"status":status,"reasons":results}
