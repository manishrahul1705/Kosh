"""Deterministic package safety and product flow; no provider execution."""
import httpx,pytest
from app.documents.downloader import DocumentDownloader,FileTooLargeError,TransientDownloadError
from app.documents.references import classify_reference
from tests.test_client_portal import portal

def test_buyer_excel_upload_is_material_boq():
 url='https://bidplus.gem.gov.in/resources/upload_nas/OctQ426/bidding/excel/bid-9992627/1791286545.xlsx'
 assert classify_reference(url,'1791286545.xlsx','Excel Upload Required: PRICE BREAKUP FORMAT - 1791286545.xlsx')==('TENDER_DOCUMENT','BOQ',True)

@pytest.mark.parametrize('context',['example spreadsheet comparison','unrelated download',''])
def test_bare_excel_upload_remains_unresolved(context):
 url='https://bidplus.gem.gov.in/resources/upload_nas/OctQ426/bidding/excel/bid-9992627/1791286545.xlsx'
 assert not classify_reference(url,'1791286545.xlsx',context)[2]

def test_explicit_nonmaterial_catalogue_does_not_override_bid_context():
 url='https://bidplus.gem.gov.in/bidding/bid/showCatalogue/abcdefghijklmnop'
 assert classify_reference(url,'General product catalogue','For reference only')[0]=='POLICY_REFERENCE'
 assert classify_reference(url,'General product catalogue','Technical Specifications as per Bid Requirement')[2]

def test_oversized_html_is_not_a_successful_truncated_page(settings,tmp_path,monkeypatch):
 import app.documents.downloader as module
 monkeypatch.setattr(module,'MAX_PAGE_BYTES',20)
 downloader=DocumentDownloader(settings,transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'text/html'},content=b'<html>'+b'x'*100+b'</html>')))
 with pytest.raises(FileTooLargeError):downloader.fetch('https://bidplus.gem.gov.in/page',tmp_path,allow_page=True)

def test_dripping_response_has_total_attempt_budget(settings,tmp_path,monkeypatch):
 import app.documents.downloader as module
 clock=[0.0]
 class Drip(httpx.SyncByteStream):
  def __iter__(self):
   for _ in range(4):
    clock[0]+=2;yield b'x'*65536
 monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
 cfg=settings.model_copy(update={'document_download_timeout_seconds':3,'document_max_retries':0})
 downloader=DocumentDownloader(cfg,transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'text/plain'},stream=Drip())))
 with pytest.raises(TransientDownloadError,match='TIMEOUT'):downloader.fetch('https://bidplus.gem.gov.in/file.txt',tmp_path)
 assert not list(tmp_path.glob('.tmp_*'))

CAT='https://bidplus.gem.gov.in/bidding/bid/showCatalogue/abcdefghijklmnop'
HTML='<html><script>doNotExecute()</script><nav>Unrelated navigation</nav><table><thead><tr><th>Category</th><th>Specification</th><th>Bid Requirement (Allowed Values)</th></tr></thead><tbody><tr><td rowspan="2">Performance</td><td>Memory</td><td>64 GB</td></tr><tr><td>Warranty</td><td>3 years</td></tr></tbody></table></html>'

def test_catalogue_static_rows_remove_navigation_and_preserve_explicit_rowspan():
 from app.documents.catalogue import catalogue_rows
 rows=catalogue_rows(HTML)
 assert rows==[['Category','Specification','Bid Requirement (Allowed Values)'],['Performance','Memory','64 GB'],['Performance','Warranty','3 years']]
 assert 'doNotExecute' not in str(rows) and 'Unrelated navigation' not in str(rows)

@pytest.mark.parametrize('html',['<html><script>dynamicOnly()</script></html>','<table><tr><td>generic product marketing</td></tr></table>',HTML.replace('64 GB','<a href="https://evil.test/spec">external specification</a>')])
def test_catalogue_missing_or_linked_requirement_cannot_be_complete(html):
 from app.documents.catalogue import catalogue_rows
 from app.documents.formats import DocumentFormatError
 with pytest.raises(DocumentFormatError):catalogue_rows(html)

def test_catalogue_download_requires_exact_endpoint_and_policy(settings,tmp_path):
 from app.documents.reference_security import AutomaticURLPolicy
 from tests.test_corpus import public_dns
 policy=AutomaticURLPolicy(settings,resolver=public_dns)
 d=DocumentDownloader(settings,transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'text/html'},text=HTML)),url_policy=policy)
 result=d.fetch(CAT,tmp_path)
 assert result.file.extension=='html' and result.file.temp_path.read_bytes().startswith(b'<html>')
 with pytest.raises(Exception):d.fetch('https://bidplus.gem.gov.in/unrelated.html',tmp_path)

@pytest.mark.parametrize('kind,key,amount',[('TURNOVER','annual_turnover',100),('EXPERIENCE','years_of_experience',1)])
def test_missing_exemption_status_requires_review_before_rejection(kind,key,amount):
 from app.eligibility.engine import EligibilityEngine
 req={'type':kind,'obligation':'MANDATORY','value_number':1000,'mse_relaxation':True,'applies_to':'BIDDER'}
 seller={'attributes':[{'key':key,'value_type':'NUMBER','value_number':amount}], 'documents':[]}
 assert EligibilityEngine().evaluate_requirement(req,seller)['status']=='REVIEW_REQUIRED'

@pytest.mark.parametrize('kind',['MSE','STARTUP'])
def test_missing_reserved_status_is_review_not_an_explicit_false(kind):
 from app.eligibility.engine import EligibilityEngine
 assert EligibilityEngine().evaluate_requirement({'type':kind,'obligation':'MANDATORY'},{'attributes':[],'documents':[]})['status']=='REVIEW_REQUIRED'

def test_portal_exposes_package_state_without_ai(portal):
 from tests.test_client_portal import A_SUB
 as_user,ids=portal
 result=as_user(A_SUB).get(f"/api/portal/sellers/{ids['a']}/tenders/{ids['soon']}")
 assert result.status_code==200
 assert result.json()['package']['completeness']=='COMPLETE'
 assert result.json()['deterministic_requirements']

def test_complete_four_type_package_without_ai(db,settings,tmp_path,session_factory):
 from datetime import timedelta
 from sqlalchemy import select,func
 from app.database.models import TenderDocument,DocumentVersion,DocumentExtraction,TenderFieldEvidence,AIAnalysisRun,TenderFieldValue,SellerRevision,SellerAttribute
 from app.database.matching_models import SellerTenderMatch
 from app.documents.documents_service import DocumentsService
 from app.documents.references import ReferenceDiscovery
 from app.extraction.service import ExtractionService
 from app.fields.service import FieldExtractionService
 from app.corpus.service import build_corpus
 from app.matching.service import MatchingService
 from app.eligibility.service import EligibilityService
 from app.services.status_service import apply_current_status
 from app.utils.dates import utcnow
 from tests.test_corpus import seed,public_dns
 from tests.pdf_factory import PdfBuilder,scanned_pdf
 from tests.test_supporting_ingestion import office_bytes
 from tests.test_ocr_ingestion import ScriptedOCR
 from tests.matching_factories import make_seller
 urls={'docx':'https://bidplus.gem.gov.in/resources/upload_nas/OctQ426/bidding/biddoc/bid-9994214/atc.docx','xlsx':'https://bidplus.gem.gov.in/resources/upload_nas/OctQ426/bidding/excel/bid-9994214/boq.xlsx','pdf':'https://bidplus.gem.gov.in/resources/upload_nas/OctQ426/bidding/biddoc/bid-9994214/qap.pdf'}
 b=PdfBuilder();p=b.page();p.text(30,30,'Bid Number: GEM/2026/B/8124821 Desktop computer tender')
 p.table(30,70,[400,100],[['Minimum Average Annual Turnover of the bidder (For 3 Years)','7 lakh']])
 for i,(kind,url) in enumerate(urls.items()):
  top=150+i*40;p.text(30,top,{'docx':'Buyer Added ATC','xlsx':'Excel Upload Required BOQ','pdf':'Quality Assurance Plan Technical Document'}[kind]);p.link(url,top=top)
 cfg,t,v=seed(db,tmp_path,settings,b.build());cfg=cfg.model_copy(update={'ocr_enabled':True})
 t.status='ONGOING';t.category='Desktop Computers';t.published_at=utcnow()-timedelta(days=1);t.bid_end_at=utcnow()+timedelta(days=2);apply_current_status(db,t,now=utcnow());db.commit()
 payload={urls['docx']:office_bytes(),urls['xlsx']:office_bytes('xlsx'),urls['pdf']:scanned_pdf(1)}
 def transport(r):
  kind=next(k for k,u in urls.items() if str(r.url)==u)
  from app.documents.formats import MIMES
  return httpx.Response(200,content=payload[str(r.url)],headers={'content-type':MIMES[kind]})
 docs=DocumentsService(cfg,transport=httpx.MockTransport(transport),sleep=lambda _:None)
 refs=ReferenceDiscovery(docs,resolver=public_dns);refs.run(db,t)
 versions=list(db.scalars(select(DocumentVersion.id).join(TenderDocument,TenderDocument.id==DocumentVersion.document_id).where(TenderDocument.tender_id==t.id)));db.commit()
 extraction=ExtractionService(cfg,session_factory,ocr_provider=ScriptedOCR())
 from app.extraction.job_queue import enqueue_extraction
 from app.extraction.job_worker import ExtractionJobWorker
 from app.fields.job_worker import FieldExtractionJobWorker
 from app.database.models import FieldExtractionJob
 for vid in versions:
  job=enqueue_extraction(db,vid,'MANUAL');db.commit()
  assert ExtractionJobWorker(cfg,session_factory,service=extraction).run_batch(job_id=job.job_id).processed==1
  db.rollback();a=db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id==vid,DocumentExtraction.is_current.is_(True)))
  assert a.status=='SUCCESS'
  field_job=db.scalar(select(FieldExtractionJob).where(FieldExtractionJob.stage3a_extraction_id==a.id));db.commit()
  assert FieldExtractionJobWorker(cfg,session_factory).run_batch(job_id=field_job.id).processed==1
 db.rollback();corpus=build_corpus(db,t.id);assert corpus['complete'],corpus['reasons'];assert len(versions)==4
 reqs,_=EligibilityService(db)._extract_tender_requirements(t.id,corpus,None)
 assert len([r for r in reqs if r['type']=='TURNOVER'])==1
 assert db.scalar(select(func.count()).select_from(AIAnalysisRun))==0
 office_version_ids=list(db.scalars(select(DocumentVersion.id).where(DocumentVersion.extension.in_(['docx','xlsx']))))
 ev=db.scalars(select(TenderFieldEvidence).where(TenderFieldEvidence.document_version_id.in_(office_version_ids),TenderFieldEvidence.field_name=='bidder_turnover_amount')).all()
 assert ev and all(e.page_number is None and 'source_location' in e.normalized_json for e in ev)
 sellers=[make_seller(db,name=name,terms='Desktop',turnover=turnover,years=5) for name,turnover in [('Strong',1000000),('Low',100),('Missing',None),('MSE',1000000),('Startup',1000000)]]
 for seller in sellers:
  rev=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller.id))
  for key in ['mse_status','startup_status']:db.add(SellerAttribute(revision_id=rev.id,key=key,value_type='BOOLEAN',value_text='TRUE' if (key=='mse_status' and seller.name=='MSE') or (key=='startup_status' and seller.name=='Startup') else 'FALSE'))
 db.commit();MatchingService(db).recalculate(now=utcnow(),seller_ids=[s.id for s in sellers],tender_ids=[t.id])
 states={m.seller_id:m.match_status for m in db.scalars(select(SellerTenderMatch).where(SellerTenderMatch.tender_id==t.id))}
 assert states[sellers[0].id]=='MATCHED' and states[sellers[1].id]=='NOT_MATCHED' and states[sellers[2].id]=='REVIEW_REQUIRED',[(m.seller_id,m.reasons_json,corpus['conflicts']) for m in db.scalars(select(SellerTenderMatch).where(SellerTenderMatch.tender_id==t.id))]
 count=db.scalar(select(func.count()).select_from(DocumentExtraction));refs.run(db,t)
 for vid in versions:extraction.extract_version(vid)
 db.rollback();assert db.scalar(select(func.count()).select_from(DocumentExtraction))==count
