"""Bounded live ingestion on a fresh read-only backup copy; no AI or source writes."""
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
    out=ROOT/'validation'/('ingestion-real-'+stamp);out.mkdir()
    source=Path(live.resolved_database_url.split('sqlite:///',1)[1])
    original=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
    original.execute('PRAGMA query_only=ON');before=original.execute('select count(*) from tenders').fetchone()[0]
    backup=out/'source-backup.db';dest=sqlite3.connect(backup);original.backup(dest)
    assert dest.execute('select count(*) from tenders').fetchone()[0]==before;dest.close()
    staging=out/'staging.db';copy=sqlite3.connect(staging);readonly=sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True);readonly.backup(copy);copy.close();readonly.close()
    cfg=live.model_copy(update={'database_url':'sqlite:///'+staging.as_posix(),'document_storage_path':str(out/'documents'),
        'lock_file':str(out/'collection.lock'),'auto_migrate':False,'scheduler_enabled':False,'collect_on_startup':False,
        'startup_recovery_enabled':False,'document_worker_enabled':False,'extraction_worker_enabled':False,
        'field_extraction_worker_enabled':False,'ai_analysis_worker_enabled':False,'ai_analysis_auto_queue':False,
        'ocr_enabled':True,'document_max_retries':1,'document_request_timeout_seconds':25})
    engine=build_engine(cfg.resolved_database_url);factory=build_session_factory(engine)
    docs=DocumentsService(cfg);extraction=ExtractionService(cfg,factory);fields=FieldExtractionService(cfg,factory)
    report={'source_database':str(source),'backup':str(backup),'staging':str(staging),'source_before':before,
            'source_writes':0,'gemini_calls':0,'targets':[]}
    def save(): (out/'results.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    save()
    for bid in ['GEM/2026/R/748499','GEM/2026/B/8118573','GEM/2026/B/8146511']:
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
        save()
    with factory() as db:
        report['staging_after']=db.scalar(select(func.count()).select_from(Tender))
        report['integrity']=db.execute(text('PRAGMA integrity_check')).scalars().all()
        report['foreign_keys']=[list(r) for r in db.execute(text('PRAGMA foreign_key_check'))]
    report['source_after']=original.execute('select count(*) from tenders').fetchone()[0];original.close();engine.dispose();save()
    print(json.dumps({'output':str(out),'source_before':before,'source_after':report['source_after'],'gemini_calls':0,'integrity':report['integrity']}))


if __name__=='__main__':main()
