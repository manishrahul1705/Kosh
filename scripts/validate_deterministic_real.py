"""Six bounded real candidates on fresh backup/staging; deterministic only, no AI."""
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from dataclasses import asdict
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import select,func,text
from app.core.config import Settings
from app.database.session import build_engine,build_session_factory
from app.database.models import Tender,TenderDocument,DocumentVersion,DocumentExtraction,DocumentPage,DocumentSection
from app.documents.documents_service import DocumentsService
from app.documents.references import ReferenceDiscovery
from app.extraction.service import ExtractionService
from app.extraction.storage import resolve_source_path
from app.fields.service import FieldExtractionService
from app.corpus.service import build_corpus


def main():
    live=Settings();stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    out=ROOT/'validation'/('deterministic-real-'+stamp);out.mkdir()
    source=Path(live.resolved_database_url.split('sqlite:///',1)[1])
    original=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
    original.execute('PRAGMA query_only=ON');before=original.execute('select count(*) from tenders').fetchone()[0]
    backup=out/'source-backup.db';dest=sqlite3.connect(backup);original.backup(dest)
    assert dest.execute('select count(*) from tenders').fetchone()[0]==before
    assert dest.execute('pragma integrity_check').fetchall()==[('ok',)]
    assert dest.execute('pragma foreign_key_check').fetchall()==[]
    dest.close()
    staging=out/'staging.db';copy=sqlite3.connect(staging);readonly=sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True);readonly.backup(copy);copy.close();readonly.close()
    cfg=live.model_copy(update={'database_url':'sqlite:///'+staging.as_posix(),'document_storage_path':str(out/'documents'),
        'lock_file':str(out/'collection.lock'),'auto_migrate':False,'scheduler_enabled':False,'collect_on_startup':False,
        'startup_recovery_enabled':False,'document_worker_enabled':False,'extraction_worker_enabled':False,
        'field_extraction_worker_enabled':False,'ai_analysis_worker_enabled':False,'ai_analysis_auto_queue':False,
        'ocr_enabled':True,'document_max_retries':1,'document_request_timeout_seconds':20,'document_download_timeout_seconds':60,
        'document_reference_max_acquisitions':20})
    engine=build_engine(cfg.resolved_database_url);factory=build_session_factory(engine)
    docs=DocumentsService(cfg);extraction=ExtractionService(cfg,factory);fields=FieldExtractionService(cfg,factory)
    report={'source_database':str(source),'backup':str(backup),'staging':str(staging),'source_before':before,
            'source_writes':0,'gemini_calls':0,'targets':[]}
    def save(): (out/'results.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    save()
    for bid in ['GEM/2026/R/748499','GEM/2026/B/8118573','GEM/2026/B/8146511','GEM/2026/B/8123378','GEM/2026/B/8124811','GEM/2026/B/8146416']:
        row={'bid':bid};report['targets'].append(row)
        with factory() as db:
            tender=db.scalar(select(Tender).where(Tender.bid_number==bid));assert tender
            tid=tender.id;row['tender_id']=tid
            old=build_corpus(db,tid);row['before']={'complete':old['complete'],'reasons':old['reasons']}
            for v in db.scalars(select(DocumentVersion).join(TenderDocument,TenderDocument.id==DocumentVersion.document_id).where(TenderDocument.tender_id==tid)):
                try:src=resolve_source_path(live.resolved_document_storage_path,v.storage_path)
                except Exception:continue
                target=cfg.resolved_document_storage_path/v.storage_path
                assert target.resolve().is_relative_to(cfg.resolved_document_storage_path.resolve())
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
            db.rollback()
            row['download']=docs.discover_and_download_tender_documents(db,tid)
            row['references']=ReferenceDiscovery(docs).run(db,tender,acquire=True,retry_failed=False)
            versions=list(db.scalars(select(DocumentVersion.id).join(TenderDocument,TenderDocument.id==DocumentVersion.document_id).where(TenderDocument.tender_id==tid,TenderDocument.is_active.is_(True),DocumentVersion.id==TenderDocument.current_version_id)))
            db.rollback()
        row['files']=[]
        for vid in versions:
            a=extraction.extract_version(vid);r={'version_id':vid,'stage3a':asdict(a)}
            if a.status in {'SUCCESS','PARTIAL_SUCCESS'}:r['stage3b']=asdict(fields.extract(a.extraction_id))
            with factory() as db:
                v=db.get(DocumentVersion,vid);d=db.get(TenderDocument,v.document_id)
                r.update(document_id=d.id,file_type=v.extension,filename=d.original_filename,source=v.source_url,sha256=v.sha256)
                r['pages']=[{'page':p.page_number or None,'method':p.text_source,'error':p.error_code,'words':p.word_count} for p in db.scalars(select(DocumentPage).where(DocumentPage.extraction_id==a.extraction_id))]
                r['ocr']=[json.loads(h.heading) for h in db.scalars(select(DocumentSection).where(DocumentSection.extraction_id==a.extraction_id,DocumentSection.detection_method=='OCR_METADATA'))]
            row['files'].append(r);save()
        with factory() as db:
            corpus=build_corpus(db,tid);row['after']=corpus
        from app.services.status_service import apply_current_status
        from app.utils.dates import utcnow
        from tests.matching_factories import make_seller
        from app.database.models import SellerRevision,SellerAttribute,EligibilityRun
        from app.database.matching_models import SellerTenderMatch
        from app.matching.service import MatchingService
        from app.api.portal import portal_tender_detail
        from app.core.supabase_auth import AuthenticatedIdentity
        from fastapi import HTTPException
        with factory() as db:
            tender=db.get(Tender,tid);apply_current_status(db,tender,now=utcnow());row['status']=tender.current_status;db.commit()
            sellers=[]
            for name,turnover in [('Strong',1000000000),('Low',1),('Incomplete',None),('MSE',1000000000),('Startup',1000000000)]:
                owner=f'validation-{tid}-{name}'
                seller=make_seller(db,name=owner,terms=tender.category or tender.title,turnover=turnover,years=100,owner_subject=owner)
                rev=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller.id))
                for key in ['mse_status','startup_status']:
                    db.add(SellerAttribute(revision_id=rev.id,key=key,value_type='BOOLEAN',value_text='TRUE' if (key=='mse_status' and name=='MSE') or (key=='startup_status' and name=='Startup') else 'FALSE'))
                sellers.append((seller.id,owner,name))
            db.commit()
            row['matching']=MatchingService(db).recalculate(now=utcnow(),seller_ids=[x[0] for x in sellers],tender_ids=[tid]).as_dict()
            row['sellers']=[]
            for sid,owner,name in sellers:
                match=db.scalar(select(SellerTenderMatch).where(SellerTenderMatch.seller_id==sid,SellerTenderMatch.tender_id==tid))
                result={'seller_id':sid,'profile':name,'match':match.match_status if match else None,'reasons':match.reasons_json if match else None}
                try:
                    detail=portal_tender_detail(sid,tid,db,AuthenticatedIdentity(subject=owner,email=None,claims={'sub':owner,'role':'authenticated'}))
                    result['portal']={'status':200,'package':detail['package'],'analysis_status':detail['analysis_status'],'deterministic_requirements':detail['deterministic_requirements']}
                except HTTPException as e:result['portal']={'status':e.status_code,'reason':e.detail}
                if match:
                    run=db.get(EligibilityRun,match.eligibility_run_id)
                    result['ai_analysis_run_id']=run.ai_analysis_run_id if run else None
                row['sellers'].append(result)
        save()
    with factory() as db:
        report['staging_after']=db.scalar(select(func.count()).select_from(Tender))
        report['integrity']=db.execute(text('PRAGMA integrity_check')).scalars().all()
        report['foreign_keys']=[list(r) for r in db.execute(text('PRAGMA foreign_key_check'))]
    report['source_after']=original.execute('select count(*) from tenders').fetchone()[0];original.close();engine.dispose();save()
    print(json.dumps({'output':str(out),'source_before':before,'source_after':report['source_after'],'gemini_calls':0,'integrity':report['integrity']}))


if __name__=='__main__':main()
