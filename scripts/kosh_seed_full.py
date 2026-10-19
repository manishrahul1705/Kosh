"""Deterministic fictional business coverage, isolated from canonical cash fixtures.

Only the one-command local setup calls this enrichment. Financial proposals stay
unconfirmed, and only approved communications execute through sandbox adapters.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from pydantic import TypeAdapter
from app.database.kosh_models import (
    KoshOperationRecord, KoshCounterparty, KoshInvoice, KoshModuleFlag,
    KoshPrivateDocument, KoshConsentArtifact, KoshCashEvent,
)
from app.database.models import Seller, SellerRevision
from app.database.auth_models import SellerMembership
from app.api.seller_authorization import AuthorizedSeller
from app.audit.ledger import append_event
from app.finance.modules import MODULES
from app.utils.dates import utcnow

AS_OF = date(2026, 10, 13)
VERSION = "business-coverage-42-v1"


def seed_full(db, seller_id: int, public_storage: Path) -> dict:
    marker = db.scalar(select(KoshOperationRecord).where(
        KoshOperationRecord.seller_id == seller_id, KoshOperationRecord.evidence_ref == VERSION))
    if marker:
        return marker.data
    owner = db.scalar(select(SellerMembership).where(
        SellerMembership.seller_id == seller_id, SellerMembership.role == "OWNER"))
    access = AuthorizedSeller(user_id=owner.user_id, seller_id=seller_id, role="OWNER")
    revision=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller_id,SellerRevision.is_active.is_(True)))
    revision.comment="Business profile and owner-recorded financial evidence"
    for module in MODULES:
        db.merge(KoshModuleFlag(seller_id=seller_id, module=module, enabled=True))
    # Keep UI-facing intake metadata neutral; documents remain fictional and
    # sandbox operation is disclosed in the README and execution banners.
    for consent in db.scalars(select(KoshConsentArtifact).where(KoshConsentArtifact.seller_id == seller_id)):
        consent.purpose = "Business cash planning and financial document intake"
    for document in db.scalars(select(KoshPrivateDocument).where(KoshPrivateDocument.seller_id == seller_id)):
        if document.status == "REVIEW":
            document.status_reason = "Held for review: instruction text detected"
    db.commit()

    from app.api import native_operations as ops
    from app.schemas.native_operations import ResourceIn, WorkflowIn
    adapter = TypeAdapter(ResourceIn)
    def resource(kind, ref, **data):
        payload = adapter.validate_python(dict(kind=kind, evidence_ref=ref, **data))
        result = ops.resource(seller_id, payload, db, access)
        ops.confirm_resource(seller_id, result["id"], db, access)
        return result["id"]
    def stored(kind, ref, data, status="CONFIRMED"):
        row = KoshOperationRecord(seller_id=seller_id, kind=kind, evidence_ref=ref,
                                  data=data, status=status, created_by_user_id=owner.user_id)
        db.add(row); db.flush()
        append_event(db, seller_id=seller_id, actor_type="HUMAN", actor_id=str(owner.user_id),
                     action="business.record", tier="T1", payload={"record_id": row.id, "kind": kind}, policy_decision="ALLOW")
        db.commit()
        return row.id

    parties = list(db.scalars(select(KoshCounterparty).where(KoshCounterparty.seller_id == seller_id).order_by(KoshCounterparty.id)))
    customers = [p for p in parties if p.kind == "CUSTOMER"]
    suppliers = [p for p in parties if p.kind == "SUPPLIER"]
    cities = ["Bengaluru", "Coimbatore", "Pune", "Chennai", "Hosur", "Mysuru"]
    for i, party in enumerate(parties):
        stored("COUNTERPARTY", f"contact:{party.id}", {"counterparty_id": party.id,
               "name": party.name, "city": cities[i % len(cities)], "contact_label": f"Accounts team, {cities[i % len(cities)]}"})
    materials = []
    for code, qty, reorder, unit_cost in [("STEEL", 180, 500, 6400), ("ALUMINIUM", 850, 400, 24800), ("CNC_INSERT", 45, 30, 185000)]:
        materials.append(resource("MATERIAL", f"stock-register:{code}", material_code=code,
                         quantity=qty, reorder_point=reorder, unit_cost_paise=unit_cost,
                         quantity_unit="KG" if code != "CNC_INSERT" else "UNIT", supplier_id=suppliers[0].id))
    resource("INVENTORY", "stock-count:2026-10-13", material_id=materials[0], quantity=180)
    goal = resource("GOAL", "finance-policy:buffer", goal="CASH_BUFFER", target_paise=100_000_000, due_date="2026-11-20")
    resource("TASK", "finance-review:october", goal_id=goal, assigned_role="FINANCE", due_date="2026-10-23")
    resource("ONBOARDING", "owner:onboarding", tracking_method="ERP", maturity="GROWING", needs=["COLLECTIONS", "INVENTORY", "REPORTS"])
    for topic, title, text in [
        ("PAYMENT_TERMS", "Receivable follow-up policy", "Finance records acceptance dates and agreed credit periods before assessing statutory interest."),
        ("SUPPLIER_POLICY", "Supplier evaluation", "Compare documented unit prices, delivery lead times and quality before purchasing."),
        ("SOP", "Dispatch reconciliation", "Match dispatched quantities to the purchase order and retain the delivery acknowledgement."),
    ]:
        resource("KNOWLEDGE", f"policy:{topic}", topic=topic, title=title, tags=["finance", "operations"], text=text)
    for code, changes in [("STEEL", ["2", "3", "5", "8"]), ("ALUMINIUM", ["1", "0", "-2", "-3"])]:
        for i, change in enumerate(changes):
            resource("MARKET_SIGNAL", f"market:{code}:{i}", material_code=code,
                     category="COMMODITY", change_percent=change,
                     observed_date=(AS_OF - timedelta(days=(3-i)*7)).isoformat(),
                     headline=f"{code.title()} procurement price observation, southern India")
    resource("STRUCTURAL_RISK", "risk:steel-stock", material_id=materials[0], risk="STOCKOUT",
             observation="Current steel stock is below the approved reorder threshold.")
    sale = ops.order(seller_id, ops.OrderIn(direction="SALE", counterparty_id=customers[0].id,
                     amount_paise=85_000_000, estimated_cost_paise=62_000_000, quantity=250,
                     payment_date=date(2026,11,20), delivery_date=date(2026,11,5), material_code="STEEL",
                     location="Bengaluru", evidence_ref="sales:SO-2026-1042"), db, access)
    po = ops.order(seller_id, ops.OrderIn(direction="PO", counterparty_id=suppliers[0].id,
                   amount_paise=32_000_000, quantity=5000, payment_date=date(2026,11,10),
                   delivery_date=date(2026,10,26), material_code="STEEL", location="Hosur",
                   evidence_ref="purchase:PO-2026-0681"), db, access)
    # A price observation proposes a delta; it does not confirm the underlying PO.
    event = KoshCashEvent(seller_id=seller_id, source_module="pricing", event_type="COST_CHANGE",
                          cost_direction="INCREASE", amount_paise=2_560_000, event_date=date(2026,11,10),
                          evidence_ref="pricing:steel-october", status="PROPOSED", created_by_user_id=owner.user_id)
    db.add(event); db.flush()
    stored("PRICE_CHANGE", "pricing:steel-october", {"purchase_order_id": po["id"], "change_percent": "8",
           "delta_paise": 2_560_000, "cash_event_id": event.id, "material_code": "STEEL"}, "PROPOSED")
    shipment = resource("SHIPMENT", "logistics:LR-2026-3901", purchase_order_id=po["id"], expected_date="2026-10-26")
    resource("SHIPMENT_STEP", "logistics:LR-2026-3901:dispatch", shipment_id=shipment,
             milestone="DISPATCHED", observed_date="2026-10-12")
    for i, supplier in enumerate(suppliers[:3]):
        rfq = ops.rfq(seller_id, ops.RFQIn(counterparty_id=supplier.id, material_code="STEEL", quantity=5000,
                      needed_date=date(2026,10,26), evidence_ref=f"rfq:steel:{supplier.id}"), db, access)
        # Quotes from different suppliers refer to their own addressed RFQ;
        # comparison also groups the common material and requested quantity.
        resource("QUOTE", f"quotation:steel:{supplier.id}", rfq_draft_id=rfq["id"], supplier_id=supplier.id,
                 price_paise=[6400,6600,6250][i], lead_days=[8,6,12][i], quality_score="0.95", reliability_score="0.92")

    from app.api import cash, collections, intelligence
    cash.run_forecast(seller_id, cash.ForecastRunIn(n_paths=2000, seed=42,
                      include_customer_history=False, include_revenue_signal=False), db, access)
    cash.backtest(seller_id, db, access)
    overdue = db.scalar(select(KoshInvoice).where(KoshInvoice.seller_id==seller_id,
                       KoshInvoice.direction=="RECEIVABLE", KoshInvoice.status=="OPEN",
                       KoshInvoice.due_date < AS_OF).order_by(KoshInvoice.due_date, KoshInvoice.id))
    if overdue is None:
        raise ValueError("Canonical business must contain an overdue open invoice")
    collections.terms(seller_id, overdue.id, collections.TermsIn(acceptance_date=overdue.invoice_date,
                      agreement_status="NONE", supplier_mse=True, evidence_ref=f"owner:delivery-ack:{overdue.invoice_number}"), db, access)
    for i, customer in enumerate(customers[:4]):
        intelligence.propose_history(seller_id, intelligence.HistoryIn(counterparty_id=customer.id,
                 observed_date=AS_OF, delay_days=[i+2,i+5,i+8], evidence_ref=f"receipts:customer:{customer.id}"), db, access)
    from app.actions.addons import create_from_draft
    from app.actions.approvals import approve, ActionError
    from app.actions.execution import execute
    from app.policy.controls import editable_control
    for state, tone in [("COMPLETED", "GENTLE"), ("APPROVAL_PAUSED", "PROFESSIONAL"), ("BLOCKED", "FIRM")]:
        draft = collections.draft(seller_id, collections.DraftIn(invoice_id=overdue.id, tone=tone), db, access)
        workflow = ops.workflow(seller_id, WorkflowIn(draft_id=draft["id"], evidence_ref=f"collections:workflow:{state}"), db, access)
        ops.advance(seller_id, workflow["id"], db, access)
        intent = create_from_draft(db, seller_id=seller_id, draft_id=draft["id"], creator_id=owner.user_id)
        db.commit()
        if state == "COMPLETED":
            _, token = approve(db, seller_id=seller_id, intent_id=intent.id, actor_id=owner.user_id); db.commit()
            execute(db, seller_id=seller_id, intent_id=intent.id, actor_id=owner.user_id, token=token); db.commit()
        elif state == "BLOCKED":
            control = editable_control(db, seller_id); control.kill_switch=True; db.commit()
            try:
                approve(db, seller_id=seller_id, intent_id=intent.id, actor_id=owner.user_id)
            except ActionError as exc:
                if exc.rule != "KILL_SWITCH": raise
                db.commit()
            finally:
                control.kill_switch=False; db.commit()
        ops.advance(seller_id, workflow["id"], db, access)

    from app.lending.service import run_evaluation
    from app.finance.plan import propose_plan
    from app.database.kosh_models import KoshPlanLine
    from app.actions.planner import create_from_plan_line
    run_evaluation(db, seller_id, AS_OF); db.commit()
    plan = propose_plan(db, seller_id, target_prob=Decimal("0.20"), target_scope="ALL_WEEKS"); db.commit()
    line = db.scalar(select(KoshPlanLine).where(KoshPlanLine.plan_id==plan.id, KoshPlanLine.required_tier=="T3"))
    if line is None: raise ValueError("Canonical T3 financing line missing")
    create_from_plan_line(db, seller_id=seller_id, plan_line_id=line.id, creator_id=owner.user_id); db.commit()
    from app.api.cash_reports import generate as report
    report(seller_id, db, access)
    from app.api.kosh_chat import reply, QuestionIn
    for question in ["Where is the cash gap?", "What does the financing plan cost?", "Which options are eligible?", "What is outstanding on invoices?"]:
        response = reply(seller_id, QuestionIn(question=question), db, access)
    from app.finance.forecast import load_inputs
    from app.finance.revenue import revenue_signal
    for days in [14, 7, 0]:
        observed=AS_OF-timedelta(days=days)
        inputs=load_inputs(db,seller_id,observed,include_addon_events=False)
        result=revenue_signal(inputs.historical_sales)
        stored("REVENUE_SIGNAL", f"revenue:{observed}", {"as_of":observed.isoformat(),
               "total_paise":sum(w['predicted_revenue_paise'] for w in result['weeks']), **result})
    seed_tenders(db, seller_id, public_storage)
    summary={"seller_id":seller_id,"modules":len(MODULES),"tenders":10,"seed":42,"as_of":AS_OF.isoformat()}
    stored("SETUP", VERSION, summary)
    return summary


def seed_tenders(db, seller_id, storage):
    from app.database.models import (Tender, TenderDocument, DocumentVersion, DocumentExtraction,
        DocumentReferenceScan, TenderFieldExtraction, TenderFieldValue, SellerAttribute, SellerDocument)
    from app.documents.references import RULES_VERSION
    from app.services.status_service import apply_current_status
    from app.database.matching_models import SellerTenderMatch
    from scripts.kosh_generate_demo import _pdf
    revision=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller_id, SellerRevision.is_active.is_(True)))
    for key,text in [("product_category","Machined Metal Components; Flanges; CNC"),("city","Bengaluru")]:
        if not db.scalar(select(SellerAttribute.id).where(SellerAttribute.revision_id==revision.id,SellerAttribute.key==key)):
            db.add(SellerAttribute(revision_id=revision.id,key=key,value_type="TEXT",value_text=text))
    for key,number in [("annual_turnover", Decimal("64873512.40")), ("years_of_experience", 12)]:
        if not db.scalar(select(SellerAttribute.id).where(SellerAttribute.revision_id==revision.id,SellerAttribute.key==key)):
            db.add(SellerAttribute(revision_id=revision.id,key=key,value_type="NUMBER",value_number=number))
    db.add(SellerDocument(revision_id=revision.id,document_type="ISO",display_name="ISO 9001 quality certificate",
                          filename="quality-certificate.pdf",status="VERIFIED",expiry_date=datetime(2027,10,13)))
    titles=["Precision CNC Flanges", "Stainless Steel Valve Bodies", "Industrial Pump Shafts", "Machined Coupling Assemblies",
            "Aluminium Instrument Housings", "Forged Steel Fasteners", "Hydraulic Cylinder End Caps", "Turbine Mounting Brackets",
            "Railway Brake Bushes", "Precision Bearing Sleeves"]
    buyers=["Bharat Heavy Electricals Limited", "Indian Railways, Southern Railway", "Hindustan Aeronautics Limited",
            "Bharat Electronics Limited", "NTPC Limited"]
    existing=db.scalar(select(Tender).where(Tender.bid_number=="GEM/2026/B/8921045"))
    for i,title in enumerate(titles):
        bid=f"GEM/2026/B/{8921045+i}"
        tender=existing if i==0 else None
        if tender is None:
            tender=Tender(bid_number=bid,first_seen_at=datetime(2026,10,13),last_seen_at=datetime(2026,10,13),source_fingerprint=hashlib.sha256(bid.encode()).hexdigest());db.add(tender)
        tender.title=f"Supply of {title}";tender.buyer_name=buyers[i%len(buyers)];tender.category="Machined Metal Components"
        tender.quantity=250+i*50;tender.estimated_value=Decimal(25_00_000+i*3_00_000)
        tender.published_at=datetime(2026,10,10);tender.bid_end_at=datetime(2026,10,26)+timedelta(days=i*3);tender.status="ONGOING"
        db.flush();apply_current_status(db,tender,now=datetime(2026,10,19))
        key=f"business/{bid.replace('/','-')}.pdf";path=storage/key;path.parent.mkdir(parents=True,exist_ok=True)
        lines=[bid,tender.title,tender.buyer_name,"Required documents: GST registration, ISO 9001 quality certificate, turnover certificate.",
               "Annual turnover required: INR 20000000. Experience required: 3 years.","ISO 9001 required. Delivery period: 45 days."]
        _pdf(path,lines)
        doc=TenderDocument(tender_id=tender.id,document_key="main_bid",document_type="MAIN_BID",display_name="Bid requirements",
                           original_filename=path.name,is_active=True);db.add(doc);db.flush()
        ver=DocumentVersion(document_id=doc.id,version_number=1,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            validation_status="VALID",extension="pdf",storage_path=key,mime_type="application/pdf",file_size=path.stat().st_size)
        db.add(ver);db.flush();doc.current_version_id=ver.id
        extraction=DocumentExtraction(document_version_id=ver.id,document_id=doc.id,tender_id=tender.id,
                    extractor_name="stage3a-v1",extractor_version="1.0.0",parser_version="1.0.0",status="SUCCESS",quality_status="GOOD",is_current=True)
        db.add(extraction);db.flush();db.add(DocumentReferenceScan(document_version_id=ver.id,status="COMPLETE",rules_version=RULES_VERSION,scanned_at=datetime(2026,10,13)))
        fields=TenderFieldExtraction(stage3a_extraction_id=extraction.id,document_version_id=ver.id,document_id=doc.id,tender_id=tender.id,
                bid_number=bid,document_type="MAIN_BID",version_number=1,extractor_name="stage3b-v1",extractor_version="1.0.0",status="SUCCESS",is_current=True)
        db.add(fields);db.flush()
        for name,number in [("turnover_required",20_000_000),("experience_required",3),("iso_9001_required",None)]:
            db.add(TenderFieldValue(field_extraction_id=fields.id,tender_id=tender.id,field_name=name,field_group="ELIGIBILITY",
                                   value_type="BOOLEAN",status="RESOLVED",tri_state="TRUE",value_number=number))
        match=db.scalar(select(SellerTenderMatch).where(SellerTenderMatch.seller_id==seller_id,SellerTenderMatch.tender_id==tender.id))
        if match is None:
            match=SellerTenderMatch(seller_id=seller_id,tender_id=tender.id,seller_revision_id=revision.id,
                relevance_status="RELEVANT",match_status="REVIEW_REQUIRED",tender_state_fingerprint=tender.source_fingerprint,matcher_version="1.0");db.add(match)
        # Financing eligibility and tender eligibility are separate: certificates
        # are required and remain subject to owner verification in this corpus.
        match.relevance_status="RELEVANT";match.match_status="REVIEW_REQUIRED";match.eligibility_status="REVIEW_REQUIRED"
        match.passed_count=2;match.review_count=1;match.matched_terms_json=json.dumps(["Machined Metal Components"])
        match.reasons_json=json.dumps([{"requirement":"Quality and turnover documents","requirement_type":"DOCUMENT",
                                        "status":"REVIEW_REQUIRED","detail":"Verify signed certificates before bidding."}])
    db.commit()
    from app.matching.service import MatchingService
    MatchingService(db).recalculate(now=datetime(2026,10,19), seller_ids=[seller_id], max_evaluations=20)
    db.commit()
