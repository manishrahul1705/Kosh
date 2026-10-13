"""Local development UI smoke server on an isolated snapshot of the soak fixture DB."""
import sqlite3, sys, shutil, argparse, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import uvicorn
from app.core.config import Settings
from app.main import create_app

parser=argparse.ArgumentParser()
parser.add_argument('--output',default='validation/ui')
parser.add_argument('--source',default='validation/soak-date-fixed/staging.db')
args=parser.parse_args()
out = (ROOT / args.output).resolve()
if not out.is_relative_to(ROOT/'validation'):raise ValueError('UI staging output must be under validation')
out.mkdir(exist_ok=True)
target = out / "staging.db"
if target.exists():
    raise RuntimeError("Preserve existing UI staging data; use it through an explicit separate run")
source_path = (ROOT / args.source).resolve()
if not source_path.is_relative_to(ROOT/'validation'):raise ValueError('UI seed must be disposable validation data')
source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
dest = sqlite3.connect(target)
source.backup(dest)
source.close(); dest.close()
shutil.copytree(source_path.parent / "documents", out / "documents")
cfg = Settings(_env_file=None, database_url="sqlite:///" + target.as_posix(),
    document_storage_path=str(out / "documents"), auto_migrate=False,
    scheduler_enabled=False, collect_on_startup=False, startup_recovery_enabled=False,
    app_env="development", dev_login_enabled=True, lock_file=str(out / "collection.lock"),
    debug_dir=str(out / "debug"), ai_provider="mock", ai_model="mock-soak", ai_api_key="",
    ai_analysis_auto_queue=False,ai_max_analyses_per_day=10000,log_level="WARNING")
# Refresh only the three fixture packages under current ingestion/prompt identities.
from sqlalchemy import select,func
from app.database.session import build_engine,build_session_factory
from app.database.models import Tender,TenderDocument
from app.documents.documents_service import DocumentsService
from app.documents.references import ReferenceDiscovery
from app.extraction.service import ExtractionService
from app.fields.service import FieldExtractionService
from app.corpus.queue import enqueue_corpus
from app.ai.service import AnalysisService
from app.ai.job_worker import AIAnalysisJobWorker
from app.ai.providers.mock import MockProvider
engine=build_engine(cfg.resolved_database_url);factory=build_session_factory(engine)
quote='The bidder must have annual turnover of INR 7 lakh.'
def response(request):
    c=next(c for c in request.chunks if quote in c['text'])
    return {'summary':'Desktop computer tender','requirements':[{'requirement_type':'TURNOVER','title':'Annual turnover',
        'obligation_level':'MANDATORY','applies_to':'BIDDER','value':7,'unit':'INR','evidence':[{'chunk_id':c['chunk_id'],'quote':quote}]}]}
provider=MockProvider(model='mock-soak',responses=[response]*10)
ai=AIAnalysisJobWorker(cfg,factory,service=AnalysisService(cfg,factory,provider_factory=lambda:provider))
with factory() as db:
    assert db.scalar(select(func.count()).select_from(Tender))<=3,'UI source must be the small fixture database'
    ids=[t.id for t in db.scalars(select(Tender))]
for tid in ids:
    with factory() as db:
        t=db.get(Tender,tid);ReferenceDiscovery(DocumentsService(cfg)).run(db,t,acquire=False)
        versions=list(db.scalars(select(TenderDocument.current_version_id).where(TenderDocument.tender_id==tid)))
    for vid in versions:
        a=ExtractionService(cfg,factory).extract_version(vid)
        assert a.extraction_id;FieldExtractionService(cfg,factory).extract(a.extraction_id)
    with factory() as db:
        job=enqueue_corpus(db,tid,cfg,force=True);db.commit();jid=job.job_id
    batch=ai.run_batch(job_id=jid)
    assert batch.processed==1,'Mock UI package analysis must actually run'
server=uvicorn.Server(uvicorn.Config(create_app(cfg,session_factory=factory),host='127.0.0.1',port=8000,log_level='warning'))
def stop_watch():
    while not server.should_exit:
        if (out/'STOP').exists():server.should_exit=True;return
        time.sleep(.5)
threading.Thread(target=stop_watch,daemon=True).start()
try:server.run()
finally:engine.dispose()
