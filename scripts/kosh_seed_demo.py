"""Idempotently seed the fictional Kosh demo through intake services."""
from __future__ import annotations

import argparse,hashlib,json,uuid,sys
from datetime import date,datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from sqlalchemy import select
from app.consent.service import create_consent,get_active_consent
from app.database.auth_models import AppUser,SellerMembership
from app.database.kosh_models import KoshCounterparty,KoshObligation,KoshPrivateDocument,KoshPrivateDocumentVersion
from app.database.models import Seller
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
        if cpse:cpse.is_cpse=True;cpse.treds_onboarded=True
        for item in json.loads((data_dir/"obligations.json").read_text(encoding="utf-8")):
            existing=session.scalar(select(KoshObligation).where(KoshObligation.seller_id==seller.id,KoshObligation.label==item["label"]))
            values={**item,"next_due_date":date.fromisoformat(item["next_due_date"])}
            if not existing:session.add(KoshObligation(seller_id=seller.id,**values))
            else:
                for key,value in values.items():setattr(existing,key,value)
        session.commit()
        from app.api.cash import get_ledger
        ledger=get_ledger(seller.id,session,None)
        result={"seller_id":seller.id,"documents_processed":processed,"review_items":review,"ledger_totals":ledger["totals"]};print(json.dumps(result,default=str,indent=2));return result
    finally:session.close()

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--database-url",default="sqlite:///./kosh_work.db");parser.add_argument("--data",type=Path,default=Path("demo_data"));parser.add_argument("--storage",type=Path,default=Path("private_storage"));args=parser.parse_args();seed(args.database_url,args.data,args.storage)
