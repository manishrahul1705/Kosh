"""At most four public attachment/catalogue probes, security policy intact, no AI."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.core.config import Settings
from app.documents.downloader import DocumentDownloader,DownloadError
from app.documents.reference_security import AutomaticURLPolicy
def main():
 out=ROOT/'validation/deterministic-20261012_213712';inventory=json.loads((out/'inventory.json').read_text())
 refs=inventory['reference_inventory']
 urls=[]
 urls.extend((x['canonical_url'],'xlsx') for x in refs if x['canonical_url'].lower().endswith('.xlsx'))
 urls=urls[:1]+[(x['canonical_url'],'catalogue') for x in refs if 'showcatalogue' in x['canonical_url'].lower()][:1]
 prior=json.loads((ROOT/'validation/ingestion-real-20261012_203432/results.json').read_text())
 for t in prior['targets']:
  for r in t['after'].get('references',[]):
   url=r.get('canonical_url',r.get('url',''))
   if 'fulfilment.gem.gov.in' in url and '.docx' in url:urls.append((url,'docx'))
 # Stored corpus representation may omit reference URL; recover the exact public URL from staging.
 if not any(kind=='docx' for _,kind in urls):
  import sqlite3
  db=sqlite3.connect((ROOT/'validation/ingestion-real-20261012_203432/staging.db').as_uri()+'?mode=ro',uri=True)
  row=db.execute("select canonical_url from document_references where canonical_url like '%fulfilment.gem.gov.in%docx%' limit 1").fetchone();db.close()
  if row:urls.append((row[0],'docx'))
 cfg=Settings().model_copy(update={'document_max_retries':0,'document_request_timeout_seconds':20,'document_download_timeout_seconds':40})
 downloader=DocumentDownloader(cfg,url_policy=AutomaticURLPolicy(cfg));results=[]
 for i,(url,kind) in enumerate(urls[:4]):
  start=time.monotonic();r={'url':url,'kind':kind}
  try:
   got=downloader.fetch(url,out/'probe-temp',allow_page=kind=='catalogue')
   r.update(status='SUCCESS',http_status=got.http_status,mime=got.content_type,final_url=got.final_url)
   if got.page_html:
    p=out/f'catalogue-{i}.html';p.write_text(got.page_html,encoding='utf8');r['html_path']=str(p);r['characters']=len(got.page_html)
   if got.file:
    p=out/f'probe-{i}.{got.file.extension}';got.file.temp_path.replace(p);r.update(file=str(p),sha256=got.file.sha256,bytes=got.file.file_size,content_disposition=got.file.content_disposition)
  except DownloadError as e:r.update(status=e.code,error=e.message)
  r['elapsed_seconds']=round(time.monotonic()-start,3);results.append(r)
  (out/'probes.json').write_text(json.dumps(results,indent=2),encoding='utf8')
 print(json.dumps(results,indent=2))
if __name__=='__main__':main()
