"""Idempotently seed the fictional Kosh demo through intake services."""
from __future__ import annotations

import argparse,hashlib,json,uuid,sys
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from sqlalchemy import select
from app.consent.service import create_consent,get_active_consent
from app.database.auth_models import AppUser,SellerMembership
from app.database.kosh_models import KoshCounterparty,KoshInvoice,KoshObligation,KoshPrivateDocument,KoshPrivateDocumentVersion
from app.database.models import Seller,SellerAttribute,SellerRevision
from app.database.session import build_engine,build_session_factory
from app.finance.intake.private_store import store_private_document
from app.finance.intake.service import process_private_document

SUBJECT=str(uuid.uuid5(uuid.UUID("6f1d3c52-2a7e-4f0b-9a51-3d6c0e0b7a10"),"demo@kosh.local"))

def seed(database_url:str,data_dir:Path,storage:Path)->dict:
    session=build_session_factory(build_engine(database_url))()
    try:
        user=session.scalar(select(AppUser).where(AppUser.supabase_user_id==SUBJECT))
        if not user:user=AppUser(supabase_user_id=SUBJECT);session.add(user);session.flush()
        seller=session.scalar(select(Seller).where(Seller.name=="Meenakshi Precision Components"))
        if not seller:seller=Seller(name="Meenakshi Precision Components");session.add(seller);session.flush()
        membership=session.scalar(select(SellerMembership).where(SellerMembership.user_id==user.id,SellerMembership.seller_id==seller.id))
        if not membership:session.add(SellerMembership(user_id=user.id,seller_id=seller.id,role="OWNER",status="ACTIVE"));session.flush()
        revision=session.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller.id,SellerRevision.is_active.is_(True)).order_by(SellerRevision.revision_number.desc()).limit(1))
        if not revision:revision=SellerRevision(seller_id=seller.id,revision_number=1,fingerprint=hashlib.sha256(b"kosh-demo-profile-v1").hexdigest(),comment="Fictional demonstration profile",is_active=True);session.add(revision);session.flush()
        attributes={"cash_buffer_paise":("NUMBER",100_000_000,"100000000","Forecast policy"),"gstin":("TEXT",None,"29ABCDE1234F1Z5","Self-declared business profile"),"udyam_number":("TEXT",None,"UDYAM-KA-03-0012345","Self-declared; certificate deliberately absent"),"udyam_category":("TEXT",None,"SMALL","Self-declared"),"incorporation_date":("TEXT",None,"2014-04-17","Self-declared"),"last_fy_turnover_paise":("NUMBER",6_487_351_240,"6487351240","FY 2025-26 self-declared"),"bank_od_limit_paise":("NUMBER",300_000_000,"300000000","Bank statement attribute"),"bank_od_utilised_paise":("NUMBER",120_000_000,"120000000","Bank statement attribute"),"credit_score_band":("TEXT",None,"SELF_DECLARED","Self-declared")}
        for key,(kind,number,text,context) in attributes.items():
            row=session.scalar(select(SellerAttribute).where(SellerAttribute.revision_id==revision.id,SellerAttribute.key==key))
            if not row:session.add(SellerAttribute(revision_id=revision.id,key=key,value_type=kind,value_number=number,value_text=text,context=context))
            else:row.value_type=kind;row.value_number=number;row.value_text=text;row.context=context
        consent=get_active_consent(session,seller.id,"BOOKS_EXPORT")
        if not consent:consent=create_consent(session,seller_id=seller.id,granted_by_user_id=user.id,purpose="Fictional Kosh demonstration",data_types=["BANK_STATEMENT","SALES_INVOICES","PURCHASE_BILLS","BOOKS_EXPORT","BUSINESS_PROFILE"],data_from=date(2024,1,1),data_to=date(2026,12,31),expires_at=datetime.utcnow()+timedelta(days=365))
        processed=review=0
        def stored(kind,path):
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            return session.execute(select(KoshPrivateDocument,KoshPrivateDocumentVersion).join(KoshPrivateDocumentVersion,KoshPrivateDocument.current_version_id==KoshPrivateDocumentVersion.id).where(KoshPrivateDocument.seller_id==seller.id,KoshPrivateDocument.kind==kind,KoshPrivateDocumentVersion.sha256==digest).limit(1)).first()
        sources=[("BOOKS_EXPORT",data_dir/"sales_register.csv"),("BOOKS_EXPORT",data_dir/"purchase_register.csv"),("BANK_STATEMENT",data_dir/"bank_statement.json")]
        for kind,path in sources:
            existing=stored(kind,path)
            if existing:document,version=existing
            else:document,version,_=store_private_document(session,seller_id=seller.id,user_id=user.id,kind=kind,filename=path.name,content=path.read_bytes(),storage_root=storage,max_bytes=10*1024*1024)
            summary=process_private_document(session,document=document,version=version,path=storage/version.storage_key,actor_id=user.id);processed+=not summary["idempotent"];review+=summary["review"]
        for path in sorted((data_dir/"invoices").glob("*.pdf")):
            kind="PURCHASE_BILL" if "poisoned" in path.name else "SALES_INVOICE"
            existing=stored(kind,path)
            if existing:document,version=existing
            else:document,version,_=store_private_document(session,seller_id=seller.id,user_id=user.id,kind=kind,filename=path.name,content=path.read_bytes(),storage_root=storage,max_bytes=10*1024*1024)
            summary=process_private_document(session,document=document,version=version,path=storage/version.storage_key,actor_id=user.id);processed+=not summary["idempotent"];review+=summary["review"]
        cpse=session.scalar(select(KoshCounterparty).where(KoshCounterparty.seller_id==seller.id,KoshCounterparty.name=="Deccan Heavy Machines Ltd (CPSE)"))
        if cpse:
            cpse.is_cpse=True;cpse.treds_onboarded=True
            for invoice in session.scalars(select(KoshInvoice).where(KoshInvoice.seller_id==seller.id,KoshInvoice.counterparty_id==cpse.id,KoshInvoice.direction=="RECEIVABLE")):invoice.accepted_by_buyer=True
        for item in json.loads((data_dir/"obligations.json").read_text(encoding="utf-8")):
            existing=session.scalar(select(KoshObligation).where(KoshObligation.seller_id==seller.id,KoshObligation.label==item["label"]))
            values={**item,"next_due_date":date.fromisoformat(item["next_due_date"])}
            if not existing:session.add(KoshObligation(seller_id=seller.id,**values))
            else:
                for key,value in values.items():setattr(existing,key,value)
        session.commit()
        from app.policy.controls import editable_control
        from app.consent.sharing import grant
        from app.utils.dates import utcnow
        control = editable_control(session, seller.id)
        parties = session.scalars(select(KoshCounterparty).where(KoshCounterparty.seller_id == seller.id)).all()
        allowlist = [{"key": f"counterparty:{p.id}", "added_at": (utcnow() - timedelta(days=2)).isoformat() + "Z"} for p in parties]
        allowlist.append({"key": "recipient:TREDS_INVOICE_DISCOUNTING", "added_at": (utcnow() - timedelta(days=2)).isoformat() + "Z"})
        allowlist.append({"key": "recipient:COLLECTIONS_PUSH", "added_at": (utcnow() - timedelta(days=2)).isoformat() + "Z"})
        allowlist.append({"key": "recipient:BANK_OD_DRAWDOWN", "added_at": (utcnow() - timedelta(days=2)).isoformat() + "Z"})
        control.allowlist = allowlist
        session.commit()
        grant(
            session,
            seller_id=seller.id,
            actor_id=user.id,
            purpose="TREDS_FINANCE",
            recipient_id="TREDS_INVOICE_DISCOUNTING",
            fields=["invoice_id", "amount_paise", "due_date"],
            expires_at=(utcnow() + timedelta(days=365)).replace(tzinfo=timezone.utc),
        )
        session.commit()
        # Seed a matched GeM tender for Tender-to-Cash scenario simulation
        from app.database.matching_models import SellerTenderMatch
        from app.database.models import Tender
        demo_bid = "GEM/2026/B/8921045"
        tender = session.scalar(select(Tender).where(Tender.bid_number == demo_bid))
        if not tender:
            now_dt = utcnow()
            tender = Tender(
                bid_number=demo_bid,
                title="Supply of Precision CNC Machined Components & Flanges",
                category="Machined Metal Components",
                buyer_name="Heavy Electricals Bharat Ltd (CPSE)",
                status="ONGOING",
                published_at=now_dt - timedelta(days=10),
                bid_end_at=now_dt + timedelta(days=35),
                first_seen_at=now_dt,
                last_seen_at=now_dt,
                source_fingerprint="kosh-demo-tender-01",
            )
            session.add(tender)
            session.flush()
        match = session.scalar(select(SellerTenderMatch).where(
            SellerTenderMatch.seller_id == seller.id,
            SellerTenderMatch.tender_id == tender.id
        ))
        if not match:
            session.add(SellerTenderMatch(
                seller_id=seller.id,
                tender_id=tender.id,
                seller_revision_id=revision.id,
                relevance_status="RELEVANT",
                eligibility_status="ELIGIBLE",
                match_status="MATCHED",
                tender_state_fingerprint="kosh-demo-tender-match-v1",
                matcher_version="1.0",
                passed_count=5,
                failed_count=0,
                review_count=0
            ))
            session.commit()
        try:
            from app.database.kosh_models import KoshForecastRun
            f_run = session.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id == seller.id, KoshForecastRun.status == "SUCCESS").limit(1))
            if f_run:
                from decimal import Decimal
                from app.lending.service import run_evaluation
                from app.finance.plan import propose_plan
                run_evaluation(session, seller.id, date(2026, 10, 13))
                session.commit()
                propose_plan(session, seller.id, target_prob=Decimal("0.20"), target_scope="ALL_WEEKS")
                session.commit()
        except Exception:
            session.rollback()
        from app.api.cash import get_ledger
        ledger=get_ledger(seller.id,session,None)
        result={"seller_id":seller.id,"documents_processed":processed,"review_items":review,"ledger_totals":ledger["totals"]};print(json.dumps(result,default=str,indent=2));return result
    finally:session.close()

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--database-url",default="sqlite:///./kosh_work.db");parser.add_argument("--data",type=Path,default=Path("demo_data"));parser.add_argument("--storage",type=Path,default=Path("private_storage"));args=parser.parse_args();seed(args.database_url,args.data,args.storage)
