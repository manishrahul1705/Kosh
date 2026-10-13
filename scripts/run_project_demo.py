"""Loopback-only, no-AI demo using a disposable copy of verified real packages."""
import argparse,json,sys,sqlite3,shutil,hashlib,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from datetime import timedelta
from sqlalchemy import select,func
from app.core.config import Settings
from app.database.session import build_engine,build_session_factory
from app.database.models import Tender,TenderDocument,DocumentVersion,SellerAttribute,SellerRevision,AIAnalysisRun,AIProviderCall
from app.database.auth_models import AppUser,SellerMembership
from app.database.matching_models import SellerTenderMatch
from app.extraction.service import ExtractionService
from app.fields.service import FieldExtractionService
from app.documents.documents_service import DocumentsService
from app.documents.references import ReferenceDiscovery
from app.corpus.service import build_corpus
from app.matching.service import MatchingService
from app.services.status_service import apply_current_status
from app.utils.dates import utcnow
from tests.pdf_factory import PdfBuilder
from tests.matching_factories import make_seller

parser=argparse.ArgumentParser();parser.add_argument('--output',default='validation/project-demo-final');parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--port',type=int,default=8000);args=parser.parse_args()
out=(ROOT/args.output).resolve()
if not out.is_relative_to(ROOT/'validation'):raise ValueError('Demo output must stay under validation')
out.mkdir(exist_ok=True);target=out/'staging.db';base=ROOT/'validation/balanced-input'
cfg=Settings(_env_file=None,database_url='sqlite:///'+target.as_posix(),document_storage_path=str(out/'documents'),
    app_env='development',dev_login_enabled=True,auto_migrate=False,scheduler_enabled=False,collect_on_startup=False,startup_recovery_enabled=False,
    document_worker_enabled=False,extraction_worker_enabled=False,field_extraction_worker_enabled=False,ai_analysis_worker_enabled=False,
    ai_analysis_auto_queue=False,ai_provider='gemini',ai_api_key='',lock_file=str(out/'collection.lock'),debug_dir=str(out/'debug'),log_level='WARNING')
fresh=not target.exists()
if fresh:
    source=sqlite3.connect((base/'staging.db').as_uri()+'?mode=ro',uri=True);dest=sqlite3.connect(target);source.backup(dest);dest.close();source.close();shutil.copytree(base/'documents',out/'documents')
    # Only the explicitly disposable copy is reduced to the three real examples.
    # Cascades retain their original document/extraction/reference identities.
    with sqlite3.connect(target) as demo:
        demo.execute('PRAGMA foreign_keys=ON')
        demo.execute('DELETE FROM tenders WHERE id NOT IN (6273,6194,6189)')
        assert not demo.execute('PRAGMA foreign_key_check').fetchall()
engine=build_engine(cfg.resolved_database_url);factory=build_session_factory(engine)
if fresh:
    with factory() as db:
        now=utcnow();t=Tender(bid_number='DEMO/FIXTURE/001',title='DEMO FIXTURE - Desktop Computers (not a GeM tender)',category='Desktop Computers',buyer_name='Demonstration fixture',status='ONGOING',published_at=now-timedelta(days=1),bid_end_at=now+timedelta(days=30),first_seen_at=now,last_seen_at=now,source_fingerprint='project-demo-fixture')
        db.add(t);db.flush();apply_current_status(db,t,now=now)
        b=PdfBuilder();page=b.page();page.text(30,30,'Demonstration fixture - not a real GeM document')
        page.table(30,70,[400,100],[['Minimum Average Annual Turnover of the bidder (For 3 Years)','7 lakh']])
        content=b.build();path=out/'documents/demo-fixture.pdf';path.write_bytes(content)
        doc=TenderDocument(tender_id=t.id,document_key='main_bid',document_type='MAIN_BID',display_name='DEMO fixture PDF',original_filename='demo-fixture.pdf');db.add(doc);db.flush()
        version=DocumentVersion(document_id=doc.id,version_number=1,sha256=hashlib.sha256(content).hexdigest(),file_size=len(content),extension='pdf',mime_type='application/pdf',storage_path='demo-fixture.pdf',validation_status='VALID');db.add(version);db.flush();doc.current_version_id=version.id;db.commit();fixture_id=t.id;vid=version.id
        ReferenceDiscovery(DocumentsService(cfg)).run(db,t,acquire=False)
    a=ExtractionService(cfg,factory).extract_version(vid);assert a.extraction_id
    f=FieldExtractionService(cfg,factory).extract(a.extraction_id);assert f.field_extraction_id
    with factory() as db:
        assert build_corpus(db,fixture_id)['complete']
        namespace=uuid.UUID('6f1d3c52-2a7e-4f0b-9a51-3d6c0e0b7a10');user=AppUser(supabase_user_id=str(uuid.uuid5(namespace,'demo@gem.local')));db.add(user);db.flush();uid=user.id;db.commit()
        seller_ids=[]
        for label,amount,years in [('Strong',1_000_000_000,100),('Low turnover',1,0),('Incomplete',None,None),('MSE',1_000_000_000,100),('Startup',1_000_000_000,100)]:
            seller=make_seller(db,name='DEMO '+label+' Seller',terms='Nvivo,Tapping screws,ROD DIA16MM,Desktop Computers',turnover=amount,years=years,oem=True,iso=label!='Incomplete')
            revision=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller.id,SellerRevision.is_active.is_(True)))
            for key in ['mse_status','startup_status']:db.add(SellerAttribute(revision_id=revision.id,key=key,value_type='BOOLEAN',value_text='TRUE' if (key=='mse_status' and label=='MSE') or (key=='startup_status' and label=='Startup') else 'FALSE'))
            db.add(SellerMembership(user_id=uid,seller_id=seller.id,role='OWNER',status='ACTIVE'));db.commit();seller_ids.append(seller.id)
        ids=[6273,6194,6189,fixture_id]
        stats=MatchingService(db).recalculate(now=utcnow(),seller_ids=seller_ids,tender_ids=ids)
        report={'demo_email':'demo@gem.local','real_tender_ids':ids[:-1],'fixture_tender_id':fixture_id,'seller_ids':seller_ids,'matching':stats.as_dict(),'ai_runs':db.scalar(select(func.count()).select_from(AIAnalysisRun)),'provider_calls':db.scalar(select(func.count()).select_from(AIProviderCall)),'matches':[{'seller_id':m.seller_id,'tender_id':m.tender_id,'state':m.match_status,'passed':m.passed_count,'failed':m.failed_count,'review':m.review_count} for m in db.scalars(select(SellerTenderMatch).where(SellerTenderMatch.seller_id.in_(seller_ids),SellerTenderMatch.tender_id.in_(ids)))]}
        fixture_states={m['state'] for m in report['matches'] if m['tender_id']==fixture_id};assert fixture_states=={'MATCHED','NOT_MATCHED','REVIEW_REQUIRED'},fixture_states
        assert db.scalar(select(func.count()).select_from(AIProviderCall))==8
        (out/'dataset.json').write_text(json.dumps(report,indent=2),encoding='utf8')
if args.prepare_only:engine.dispose();print('Prepared isolated no-AI demo');sys.exit(0)
stop=out/'STOP'
if stop.exists():stop.unlink()
import uvicorn
from app.main import create_app
server=uvicorn.Server(uvicorn.Config(create_app(cfg,session_factory=factory),host='127.0.0.1',port=args.port,log_level='warning'))
def watcher():
    while not server.should_exit:
        if stop.exists():server.should_exit=True;return
        time.sleep(.5)
threading.Thread(target=watcher,daemon=True).start()
try:server.run()
finally:engine.dispose()
