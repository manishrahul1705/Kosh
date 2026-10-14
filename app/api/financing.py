"""Seller-authorized financing evaluation and plan endpoints."""
from datetime import date
from decimal import Decimal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit,require_seller_read,require_seller_owner
from app.audit.ledger import append_event
from app.core.config import get_settings
from app.database.models import SellerRevision,SellerAttribute,SellerDocument
from app.database.kosh_models import KoshCounterparty,KoshFinancingEvaluation,KoshFinancingResult,KoshPlan,KoshPlanLine,KoshForecastRun
from app.finance.plan import propose_plan
from app.finance.costs import financing_quote
from app.lending.catalogue import load_catalogue
from app.lending.service import run_evaluation,_attributes,_attribute_sources
from app.utils.dates import utcnow

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}",tags=["kosh-financing"])
SORT_RULE="sorted by effective annual cost, lowest first; no provider pays for placement"
def _as_of():return date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat())
def _latest_eval(db,seller):return db.scalar(select(KoshFinancingEvaluation).where(KoshFinancingEvaluation.seller_id==seller).order_by(KoshFinancingEvaluation.id.desc()).limit(1))
def _result(row,products):
    product=products[row.product_id];return {"product_id":row.product_id,"display_name":product["display_name"],"provider_label":product["provider_label"],"scope":row.scope,"status":row.status,"max_amount_paise":row.max_amount_paise,"effective_annual_rate":row.effective_annual_rate,"arrival_business_days":row.arrival_business_days,"reasons":row.reasons,"evidence":row.evidence,"assumption":product["cost_model"].get("assumption",False),**financing_quote(product,row.max_amount_paise),"quote_basis":"90-day quote basis","cost_assumption":product["cost_model"].get("assumption_label","Illustrative catalogue terms"),"verify_before_relying":any(not c.get("source",{}).get("verified",False) for c in product["criteria"])}
@router.post("/financing/evaluate")
def evaluate(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=run_evaluation(db,seller_id,_as_of())
    except ValueError as exc:raise HTTPException(409,str(exc))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="financing.evaluate",tier="T1_DRAFT",payload={"evaluation_id":row.id},policy_decision="ALLOW");db.commit();return {"evaluation_id":row.id}
@router.get("/financing/options")
def options(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    ev=_latest_eval(db,seller_id);products={p["id"]:p for p in load_catalogue()};rows=[] if not ev else [_result(x,products) for x in db.scalars(select(KoshFinancingResult).where(KoshFinancingResult.evaluation_id==ev.id))]
    grouped=[]
    for product_id,product in products.items():
        candidates=[x for x in rows if x["product_id"]==product_id]
        if not candidates:continue
        matched=[x for x in candidates if x["status"]=="MATCHED"]
        selected=(matched or [x for x in candidates if x["status"]=="REVIEW_REQUIRED"] or candidates)[0]
        if product_id in {"COLLECTIONS_PUSH","TREDS_INVOICE_DISCOUNTING","SUPPLIER_TERM_EXTENSION"}:
            amount=min(product["max_amount_paise"],sum(x["max_amount_paise"] for x in matched))
            selected={**selected,**financing_quote(product,amount),"max_amount_paise":amount,"invoice_eligibility":[{"scope":x["scope"],"status":x["status"],"eligible":x["status"]=="MATCHED","max_amount_paise":x["max_amount_paise"],"reasons":x["reasons"],"evidence":x["evidence"]} for x in candidates if x["scope"]]}
        grouped.append(selected)
    rows=grouped
    rows.sort(key=lambda x:(Decimal(x["effective_annual_rate"] or "999"),x["product_id"]));return {"seller_id":seller_id,"sort_rule":SORT_RULE,"items":rows}
@router.get("/financing/options/{product_id}/explain")
def explain(seller_id:int,product_id:str,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    data=options(seller_id,db,access);matches=[x for x in data["items"] if x["product_id"]==product_id]
    if not matches:raise HTTPException(404,"Product result not found")
    return {"product_id":product_id,"status":matches[0]["status"],"explanation":" ".join(r["reason"] for x in matches for r in x["reasons"])}
def _line_out(line):
    result={c.name:getattr(line,c.name) for c in line.__table__.columns}
    for evidence in line.evidence:
        for key in ("days","funding_date","repayment_date","repayment_assumption"):
            if key in evidence:result[key]=evidence[key]
    return result

def _plan_out(db,row):
    from app.finance.plan_freshness import display_status
    status=display_status(db,row);details=dict(row.planning_details)
    if status=='STALE':details['baseline_status']='STALE';details['why_this_plan']='Forecast inputs or the selected basis changed. Re-evaluate financing and build a current plan.'
    lines=db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id==row.id)).all();return {"id":row.id,"seller_id":row.seller_id,"forecast_run_id":row.forecast_run_id,"forecast_fingerprint":row.forecast_fingerprint,"method":row.method,"status":status,"total_cost_paise":row.total_cost_paise,"baseline_cost_paise":row.baseline_cost_paise,"before_probabilities":row.before_probabilities,"after_probabilities":row.after_probabilities,"planning_details":details,"target_probability":row.planning_details.get("target_probability"),"why_this_plan":details.get("why_this_plan") or next((e["why_this_plan"] for line in lines for e in line.evidence if "why_this_plan" in e),"No eligible capacity was selected."),"lines":[_line_out(x) for x in lines]}
class PlanIn(BaseModel):
    target_probability:Decimal|None=Field(default=None,ge=0,lt=1)
    loan_repayment_date:date|None=None

@router.get("/financing/safety-curve")
def safety_curve(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    try:items=[propose_plan(db,seller_id,target_prob=target,persist=False) for target in (Decimal(".40"),Decimal(".30"),Decimal(".20"),Decimal(".10"))]
    except ValueError as exc:raise HTTPException(409,str(exc))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="plan.safety_curve.read",tier="T0_READ",payload={"targets":[x["target_probability"] for x in items]},policy_decision="ALLOW")
    db.commit()
    return {"seller_id":seller_id,"default_target_probability":str(get_settings().kosh_plan_target_prob),"items":items}

@router.post("/plans")
def create_plan(seller_id:int,payload:PlanIn=PlanIn(),db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=propose_plan(db,seller_id,target_prob=payload.target_probability,loan_repayment_date=payload.loan_repayment_date)
    except ValueError as exc:raise HTTPException(409,str(exc))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="plan.propose",tier="T1_DRAFT",payload={"plan_id":row.id,"target_probability":row.planning_details["target_probability"],"loan_repayment_date":payload.loan_repayment_date},policy_decision="ALLOW");db.commit();return {"plan_id":row.id}
@router.get("/plans/latest")
def latest(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=db.scalar(select(KoshPlan).where(KoshPlan.seller_id==seller_id).order_by(KoshPlan.id.desc()).limit(1))
    if not row:raise HTTPException(404,"No plan")
    return _plan_out(db,row)
@router.get("/plan")
def plan_compatibility(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=db.scalar(select(KoshPlan).where(KoshPlan.seller_id==seller_id).order_by(KoshPlan.id.desc()).limit(1))
    return _plan_out(db,row) if row else {"seller_id":seller_id,"status":"NOT_IMPLEMENTED","items":[]}
@router.get("/plans/{plan_id}")
def detail(seller_id:int,plan_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=db.scalar(select(KoshPlan).where(KoshPlan.id==plan_id,KoshPlan.seller_id==seller_id))
    if not row:raise HTTPException(404,"Plan not found")
    return _plan_out(db,row)

FIXTURES = {
    "FICT-MATCH-001": {
        "id": "FICT-MATCH-001",
        "label": "Legitimate Match (Mudra / CGTMSE)",
        "description": "Fictional fixture with complete, confirmed evidence satisfying all MUDRA and CGTMSE criteria (non-corporate, non-farm, income-generating, MSE status, and verified Udyam certificate).",
        "evidence": {
            "non_corporate": True,
            "non_farm": True,
            "income_generating": True,
            "micro_small_enterprise": True,
            "tarun_availed_and_repaid": True,
            "udyam_certificate_present": True,
            "gem_po_document": False,
            "supplier_relationship_months": 24,
            "supplier_on_time_ratio": 0.95,
            "supplier_extension_status": "CONFIRMED",
            "evidence_ref": "fictional-fixture:udyam-cert-verified-2026",
        },
    },
    "FICT-FAIL-002": {
        "id": "FICT-FAIL-002",
        "label": "Confirmed Evidence Failing Criterion",
        "description": "Fictional fixture where confirmed evidence explicitly fails scheme criteria: entity is an agricultural farm enterprise (fails PMMY non-farm rule), and supplier relationship is 6 months with 65% on-time ratio (fails 12-month and 80% thresholds).",
        "evidence": {
            "non_corporate": True,
            "non_farm": False,
            "income_generating": True,
            "micro_small_enterprise": True,
            "tarun_availed_and_repaid": False,
            "udyam_certificate_present": False,
            "gem_po_document": False,
            "supplier_relationship_months": 6,
            "supplier_on_time_ratio": 0.65,
            "supplier_extension_status": "UNKNOWN",
            "evidence_ref": "fictional-fixture:farm-credit-and-new-supplier",
        },
    },
    "FICT-REVIEW-003": {
        "id": "FICT-REVIEW-003",
        "label": "Incomplete Evidence Remaining in Review",
        "description": "Fictional fixture where entity has confirmed non-corporate status, but all other sector, activity, document, and supplier history facts remain unrecorded/unknown.",
        "evidence": {
            "non_corporate": True,
            "non_farm": None,
            "income_generating": None,
            "micro_small_enterprise": None,
            "tarun_availed_and_repaid": None,
            "udyam_certificate_present": None,
            "gem_po_document": None,
            "supplier_relationship_months": None,
            "supplier_on_time_ratio": None,
            "supplier_extension_status": "UNKNOWN",
            "evidence_ref": "fictional-fixture:partial-declaration",
        },
    },
    "FICT-SUPPLIER-PROPOSED": {
        "id": "FICT-SUPPLIER-PROPOSED",
        "label": "Supplier Extension: Unconfirmed Proposal",
        "description": "Proposed 30-day payment extension sent to supplier; pending supplier confirmation. Crucially, a proposal alone does NOT change payable due dates or create cash receipts.",
        "evidence": {
            "supplier_relationship_months": 18,
            "supplier_on_time_ratio": 0.90,
            "supplier_extension_status": "PROPOSED",
            "evidence_ref": "fictional-fixture:draft-supplier-request-no-payment-date-change",
        },
    },
    "FICT-SUPPLIER-CONFIRMED": {
        "id": "FICT-SUPPLIER-CONFIRMED",
        "label": "Supplier Extension: Confirmed Agreement",
        "description": "Confirmed supplier agreement with signed credit addendum extending terms. Payment dates remain guarded by standard approval and ledger controls.",
        "evidence": {
            "supplier_relationship_months": 18,
            "supplier_on_time_ratio": 0.90,
            "supplier_extension_status": "CONFIRMED",
            "evidence_ref": "fictional-fixture:supplier-signed-addendum-2026",
        },
    },
}

class FinancingEvidenceIn(BaseModel):
    non_corporate: bool | None = None
    non_farm: bool | None = None
    income_generating: bool | None = None
    micro_small_enterprise: bool | None = None
    tarun_availed_and_repaid: bool | None = None
    udyam_certificate_present: bool | None = None
    gem_po_document: bool | None = None
    supplier_id: int | None = None
    supplier_relationship_months: int | None = Field(default=None, ge=0)
    supplier_on_time_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    supplier_extension_status: str | None = Field(default=None, pattern="^(PROPOSED|CONFIRMED|UNKNOWN)$")
    evidence_ref: str | None = Field(default=None, max_length=160)
    apply_fixture: str | None = None

@router.get("/financing/evidence")
def get_financing_evidence(seller_id: int, db: Session = Depends(get_db), access: AuthorizedSeller = Depends(require_seller_read)):
    rev, a, docs = _attributes(db, seller_id)
    sources = _attribute_sources(db, seller_id)
    as_of = _as_of()

    def _bool_or_none(k):
        v = a.get(k)
        if v is None: return None
        s = str(v).lower()
        if s in {"true", "1", "yes"}: return True
        if s in {"false", "0", "no"}: return False
        return None

    def _num_or_none(k, cast_fn):
        v = a.get(k)
        if v is None: return None
        try: return cast_fn(v)
        except (ValueError, TypeError): return None

    udyam_doc = db.scalar(select(SellerDocument).where(SellerDocument.revision_id == rev.id, SellerDocument.document_type == "UDYAM_CERTIFICATE")) if rev else None
    if udyam_doc:
        udyam_status = "VERIFIED" if udyam_doc.status == "VERIFIED" else "LINKED_DOCUMENT"
        udyam_val = True
    elif a.get("udyam_certificate_present") is not None:
        udyam_status = "DECLARATION_ONLY"
        udyam_val = _bool_or_none("udyam_certificate_present")
    else:
        udyam_status = "NEEDS_DOCUMENTATION"
        udyam_val = None

    evidence = {
        "non_corporate": _bool_or_none("non_corporate"),
        "non_farm": _bool_or_none("non_farm"),
        "income_generating": _bool_or_none("income_generating"),
        "micro_small_enterprise": _bool_or_none("micro_small_enterprise"),
        "tarun_availed_and_repaid": _bool_or_none("tarun_availed_and_repaid"),
        "udyam_certificate_present": udyam_val,
        "udyam_certificate_status": udyam_status,
        "gem_po_document": True if ("GEM_PO" in docs or "PURCHASE_ORDER" in docs) else (_bool_or_none("gem_po_document") if a.get("gem_po_document") is not None else _bool_or_none("document_present")),
        "supplier_relationship_months": _num_or_none("supplier_relationship_months", int),
        "supplier_on_time_ratio": _num_or_none("supplier_on_time_ratio", float),
        "supplier_extension_status": str(a.get("supplier_extension_status") or "UNKNOWN").upper(),
        "evidence_ref": a.get("financing_evidence_ref"),
        "recorded_at": a.get("financing_evidence_recorded_at"),
    }

    missing = [
        {
            "product_id": "MUDRA_LOAN",
            "display_name": "MUDRA loan",
            "product_support_status": "IMPLEMENTED",
            "criteria": [
                {"criterion": "NON_CORPORATE", "label": "Non-corporate constitution", "status": "CONFIRMED" if evidence["non_corporate"] is not None else "MISSING", "value": evidence["non_corporate"], "evidence_required": "Proprietorship / partnership deed or constitutional self-declaration", "supported": True},
                {"criterion": "NON_FARM", "label": "Non-farm enterprise sector", "status": "CONFIRMED" if evidence["non_farm"] is not None else "MISSING", "value": evidence["non_farm"], "evidence_required": "NIC code / sector declaration excluding agricultural farming", "supported": True},
                {"criterion": "INCOME_GENERATING", "label": "Income-generating business purpose", "status": "CONFIRMED" if evidence["income_generating"] is not None else "MISSING", "value": evidence["income_generating"], "evidence_required": "Commercial revenue activity declaration", "supported": True},
                {"criterion": "MICRO_SMALL_ENTERPRISE", "label": "Micro / Small enterprise classification", "status": "CONFIRMED" if evidence["micro_small_enterprise"] is not None else "MISSING", "value": evidence["micro_small_enterprise"], "evidence_required": "MSMED Act enterprise classification declaration", "supported": True},
            ],
        },
        {
            "product_id": "CGTMSE_BACKED_WC_LOAN",
            "display_name": "CGTMSE-backed working capital loan",
            "product_support_status": "IMPLEMENTED",
            "criteria": [
                {"criterion": "UDYAM_CERTIFICATE_PRESENT", "label": "Udyam Registration Certificate", "status": udyam_status, "value": evidence["udyam_certificate_present"], "evidence_required": "Uploaded Udyam Certificate document or independently verified certificate reference (owner declaration alone is insufficient)", "supported": True},
            ],
        },
        {
            "product_id": "GEM_SAHAY_PO_FINANCE",
            "display_name": "GeM Sahay PO finance",
            "product_support_status": "UNDER_REVISION",
            "criteria": [
                {"criterion": "DOCUMENT_PRESENT", "label": "GeM Purchase Order", "status": "CONFIRMED" if evidence["gem_po_document"] is not None else "MISSING", "value": evidence["gem_po_document"], "evidence_required": "GeM Purchase Order / contract document reference", "supported": True},
                {"criterion": "PRODUCT_STATUS", "label": "Primary-source verified terms", "status": "UNSUPPORTED", "value": None, "evidence_required": "Lender API integration and primary-source verified terms (unverified in catalogue)", "supported": False},
            ],
        },
        {
            "product_id": "SUPPLIER_TERM_EXTENSION",
            "display_name": "Supplier term extension",
            "product_support_status": "IMPLEMENTED",
            "criteria": [
                {"criterion": "SUPPLIER_RELATIONSHIP_MIN_MONTHS", "label": "Supplier trading relationship tenure (>= 12 months)", "status": "CONFIRMED" if evidence["supplier_relationship_months"] is not None else "MISSING", "value": evidence["supplier_relationship_months"], "evidence_required": "Documented ledger / supplier account opening date (min 12 months)", "supported": True},
                {"criterion": "SUPPLIER_ON_TIME_RATIO_MIN", "label": "Supplier on-time payment track record (>= 80%)", "status": "CONFIRMED" if evidence["supplier_on_time_ratio"] is not None else "MISSING", "value": evidence["supplier_on_time_ratio"], "evidence_required": "Historical payment track record / bank proof (min 80% on-time)", "supported": True},
                {"criterion": "SUPPLIER_AGREEMENT_CONFIRMED", "label": "Confirmed supplier agreement vs unconfirmed proposal", "status": "CONFIRMED" if evidence["supplier_extension_status"] == "CONFIRMED" else "PROPOSAL" if evidence["supplier_extension_status"] == "PROPOSED" else "MISSING", "value": evidence["supplier_extension_status"], "evidence_required": "Signed supplier addendum (proposal alone does not change payment dates)", "supported": True},
            ],
        },
    ]

    return {
        "seller_id": seller_id,
        "role": access.role,
        "as_of": as_of.isoformat(),
        "evidence": evidence,
        "sources": sources,
        "missing_criteria": missing,
        "fixtures": list(FIXTURES.values()),
    }

@router.put("/financing/evidence")
def set_financing_evidence(seller_id: int, payload: FinancingEvidenceIn, db: Session = Depends(get_db), access: AuthorizedSeller = Depends(require_seller_owner)):
    as_of = _as_of()
    data = payload.dict()
    if payload.apply_fixture:
        fix = FIXTURES.get(payload.apply_fixture)
        if not fix:
            raise HTTPException(400, f"Unknown fixture: {payload.apply_fixture}")
        data.update(fix["evidence"])
        data["evidence_ref"] = fix["evidence"].get("evidence_ref") or f"fixture:{payload.apply_fixture}"

    rev = db.scalar(select(SellerRevision).where(SellerRevision.seller_id == seller_id, SellerRevision.is_active.is_(True)).order_by(SellerRevision.revision_number.desc()).limit(1))
    if not rev:
        rev = SellerRevision(seller_id=seller_id, revision_number=1, fingerprint=f"kosh-seller-{seller_id}", is_active=True, comment="Kosh financing profile")
        db.add(rev)
        db.flush()

    # Handle fixture document artifacts
    if payload.apply_fixture == "FICT-MATCH-001":
        doc = db.scalar(select(SellerDocument).where(SellerDocument.revision_id == rev.id, SellerDocument.document_type == "UDYAM_CERTIFICATE"))
        if not doc:
            doc = SellerDocument(revision_id=rev.id, document_type="UDYAM_CERTIFICATE", display_name="Udyam Certificate", filename="fict_udyam_cert_verified_2026.pdf", status="VERIFIED")
            db.add(doc)
        else:
            doc.status = "VERIFIED"
    elif payload.apply_fixture:
        # Clear fixture document if applying other fixtures
        for d in db.scalars(select(SellerDocument).where(SellerDocument.revision_id == rev.id, SellerDocument.document_type == "UDYAM_CERTIFICATE", SellerDocument.filename == "fict_udyam_cert_verified_2026.pdf")).all():
            db.delete(d)

    now_iso = utcnow().isoformat()
    ref = data.get("evidence_ref") or "Declared by owner"
    context = f"Owner-entered evidence; ref: {ref}; recorded: {now_iso}; user: {access.user_id}"

    def _set_attr(key: str, vtype: str, text: str | None = None, number: float | None = None):
        attr = db.scalar(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id, SellerAttribute.key == key))
        if not attr:
            attr = SellerAttribute(revision_id=rev.id, key=key, value_type=vtype, value_text=text, value_number=number, context=context, created_at=utcnow())
            db.add(attr)
        else:
            attr.value_type = vtype
            attr.value_text = text
            attr.value_number = number
            attr.context = context
            attr.created_at = utcnow()

    bool_keys = ["non_corporate", "non_farm", "income_generating", "micro_small_enterprise", "tarun_availed_and_repaid", "udyam_certificate_present", "gem_po_document"]
    for k in bool_keys:
        if k in data:
            v = data[k]
            if v is not None:
                _set_attr(k, "BOOLEAN", text="TRUE" if v else "FALSE")
            elif payload.apply_fixture or k in payload.__fields_set__:
                attr = db.scalar(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id, SellerAttribute.key == k))
                if attr: db.delete(attr)

    supplier_id = payload.supplier_id
    all_suppliers = db.scalars(select(KoshCounterparty).where(KoshCounterparty.seller_id == seller_id, KoshCounterparty.kind == "SUPPLIER")).all()
    if supplier_id is None and len(all_suppliers) == 1:
        supplier_id = all_suppliers[0].id

    if "supplier_relationship_months" in data:
        v = data["supplier_relationship_months"]
        if v is not None:
            _set_attr("supplier_relationship_months", "NUMBER", number=float(v))
            if supplier_id is not None:
                _set_attr(f"supplier_{supplier_id}_relationship_months", "NUMBER", number=float(v))
        elif payload.apply_fixture or "supplier_relationship_months" in payload.__fields_set__:
            attr = db.scalar(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id, SellerAttribute.key == "supplier_relationship_months"))
            if attr: db.delete(attr)
            if supplier_id is not None:
                attr_s = db.scalar(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id, SellerAttribute.key == f"supplier_{supplier_id}_relationship_months"))
                if attr_s: db.delete(attr_s)

    if "supplier_on_time_ratio" in data:
        v = data["supplier_on_time_ratio"]
        if v is not None:
            _set_attr("supplier_on_time_ratio", "NUMBER", number=float(v))
            if supplier_id is not None:
                _set_attr(f"supplier_{supplier_id}_on_time_ratio", "NUMBER", number=float(v))
        elif payload.apply_fixture or "supplier_on_time_ratio" in payload.__fields_set__:
            attr = db.scalar(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id, SellerAttribute.key == "supplier_on_time_ratio"))
            if attr: db.delete(attr)
            if supplier_id is not None:
                attr_s = db.scalar(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id, SellerAttribute.key == f"supplier_{supplier_id}_on_time_ratio"))
                if attr_s: db.delete(attr_s)

    if "supplier_extension_status" in data:
        v = data["supplier_extension_status"]
        if v is not None:
            _set_attr("supplier_extension_status", "TEXT", text=str(v).upper())
            if supplier_id is not None:
                _set_attr(f"supplier_{supplier_id}_extension_status", "TEXT", text=str(v).upper())
        elif payload.apply_fixture or "supplier_extension_status" in payload.__fields_set__:
            attr = db.scalar(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id, SellerAttribute.key == "supplier_extension_status"))
            if attr: db.delete(attr)
            if supplier_id is not None:
                attr_s = db.scalar(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id, SellerAttribute.key == f"supplier_{supplier_id}_extension_status"))
                if attr_s: db.delete(attr_s)

    _set_attr("financing_evidence_ref", "TEXT", text=ref)
    _set_attr("financing_evidence_recorded_at", "TEXT", text=now_iso)
    if supplier_id is not None:
        _set_attr(f"supplier_{supplier_id}_evidence_ref", "TEXT", text=ref)

    append_event(
        db,
        seller_id=seller_id,
        actor_type="HUMAN",
        actor_id=str(access.user_id),
        action="financing.evidence",
        tier="T1_DRAFT",
        payload={
            "evidence_ref": ref,
            "recorded_at": now_iso,
            "fields": {k: data[k] for k in data if data[k] is not None},
        },
        policy_decision="ALLOW",
    )

    for plan in db.scalars(select(KoshPlan).where(KoshPlan.seller_id == seller_id, KoshPlan.status == "VALID")).all():
        plan.status = "STALE"
        details = dict(plan.planning_details)
        details["why_this_plan"] = "Financing eligibility evidence changed. Re-evaluate financing and build a current plan."
        plan.planning_details = details

    db.flush()

    try:
        eval_row = run_evaluation(db, seller_id, as_of)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    db.commit()

    return {
        "status": "RECORDED",
        "seller_id": seller_id,
        "evaluation_id": eval_row.id,
        "as_of": as_of.isoformat(),
        "evidence_ref": ref,
        "options": options(seller_id, db, access)["items"],
    }
