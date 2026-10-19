"""Rebuild the disposable Kosh working database from the newest local backup."""
from __future__ import annotations
import json,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.audit.verify import verify_chain
from app.database.session import build_engine,build_session_factory
from scripts.kosh_generate_demo import generate
from scripts.kosh_seed_demo import seed

def main()->None:
    backups=sorted((ROOT/"backups").glob("*.db"),key=lambda path:path.stat().st_mtime,reverse=True)
    if not backups:raise RuntimeError("No database backup found")
    target=ROOT/"kosh_work.db"
    if target.exists():target.unlink()
    source=sqlite3.connect(f"file:{backups[0].as_posix()}?mode=ro",uri=True);destination=sqlite3.connect(target)
    try:source.backup(destination)
    finally:source.close();destination.close()
    subprocess.run([sys.executable,"-m","alembic","upgrade","head"],cwd=ROOT,check=True)
    manifest=generate(42,ROOT/"demo_data",date.fromisoformat("2026-10-13"))
    result=seed("sqlite:///./kosh_work.db",ROOT/"demo_data",ROOT/"private_storage")
    session=build_session_factory(build_engine("sqlite:///./kosh_work.db"))()
    try:audit=verify_chain(session).__dict__
    finally:session.close()
    print(json.dumps({"source_backup":str(backups[0]),"manifest":manifest,"seed":result,"audit":audit},default=str,indent=2))

if __name__=="__main__":
    from datetime import date
    main()
