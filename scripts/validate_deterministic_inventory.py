"""Fresh read-only SQLite backup and bounded document/reference inventory; no AI."""
import json,sqlite3,sys
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.core.config import Settings

def main():
 s=Settings();out=ROOT/'validation'/('deterministic-'+datetime.now().strftime('%Y%m%d_%H%M%S'));out.mkdir()
 source=Path(s.resolved_database_url.split('sqlite:///',1)[1])
 db=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=30);db.execute('PRAGMA query_only=ON')
 backup=out/'source-backup.db';target=sqlite3.connect(backup);db.backup(target)
 result={'source':str(source),'output':str(out),'count':db.execute('select count(*) from tenders').fetchone()[0],
 'revision':target.execute('select version_num from alembic_version').fetchall(),
 'integrity':target.execute('pragma integrity_check').fetchall(),'foreign_keys':target.execute('pragma foreign_key_check').fetchall()}
 target.row_factory=sqlite3.Row
 result['reference_inventory']=[dict(r) for r in target.execute('select * from document_references limit 5000')]
 result['candidates']=[dict(r) for r in target.execute("select * from tenders where bid_number in ('GEM/2026/R/748499','GEM/2026/B/8118573','GEM/2026/B/8146511') or id in (select id from tenders where bid_number like '%/B/%' order by id desc limit 8)")]
 result['versions']=[dict(r) for r in target.execute('select extension,count(*) n from document_versions group by extension')]
 target.close();db.close()
 (out/'inventory.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf8')
 print(json.dumps({'output':str(out),'count':result['count'],'integrity':result['integrity'],'revision':result['revision'],'references':len(result['reference_inventory']),'types':result['versions']}))
if __name__=='__main__':main()
