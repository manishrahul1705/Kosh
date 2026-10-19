"""One-command offline business setup after installing Python dependencies."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAFE_ENV = dict(SCHEDULER_ENABLED="false", AUTO_MIGRATE="false", COLLECT_ON_STARTUP="false",
                STARTUP_RECOVERY_ENABLED="false", APP_ENV="development", KOSH_AS_OF_DATE="2026-10-13")


def setup(database_url=None, *, reset=False, root=ROOT, configure_env=True, public_storage=None):
    if configure_env:
        os.environ.update(SAFE_ENV)
    from app.database.session import run_migrations, build_engine, build_session_factory
    from app.core.config import get_settings
    from scripts.kosh_generate_demo import generate
    from scripts.kosh_seed_demo import seed
    from scripts.kosh_seed_full import seed_full, AS_OF, VERSION
    from app.database.kosh_models import KoshOperationRecord
    from sqlalchemy import select
    database_url = database_url or f"sqlite:///{(root / 'kosh_work.db').as_posix()}"
    frontend_config=root/'frontend/.env.development.local'
    if frontend_config.parent.is_dir():
        import re
        text=frontend_config.read_text(encoding='utf-8') if frontend_config.exists() else ''
        if re.search(r'^VITE_DEV_LOGIN=',text,re.M):
            text=re.sub(r'^VITE_DEV_LOGIN=.*$', 'VITE_DEV_LOGIN=true',text,flags=re.M)
        else:
            text=text.rstrip()+'\nVITE_DEV_LOGIN=true\n'
        frontend_config.write_text(text,encoding='utf-8')
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Local setup requires an explicitly selected SQLite file")
    path=Path(database_url[len("sqlite:///"):])
    if not path.is_absolute(): path=root/path
    path=path.resolve()
    if reset:
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Reset database must be inside the selected repository workspace")
        for target in (path, Path(str(path)+"-wal"), Path(str(path)+"-shm")):
            if target.is_file(): target.unlink()
    path.parent.mkdir(parents=True,exist_ok=True)
    url=f"sqlite:///{path.as_posix()}"
    run_migrations(url)
    engine=build_engine(url)
    try:
        with build_session_factory(engine)() as db:
            marker=db.scalar(select(KoshOperationRecord).where(KoshOperationRecord.evidence_ref==VERSION))
            if marker: return marker.data
        data=root/'demo_data';storage=root/'private_storage'
        generate(seed=42,out=data,as_of=AS_OF)
        result=seed(url,data,storage)
        with build_session_factory(engine)() as db:
            return seed_full(db,result['seller_id'],public_storage or get_settings().resolved_document_storage_path)
    finally:
        engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url')
    parser.add_argument('--reset',action='store_true',help='Restore the selected local database; stop its server first')
    args=parser.parse_args()
    result=setup(args.database_url,reset=args.reset)
    print(f"Business workspace ready: Meenakshi Precision Components (seller {result['seller_id']})")
    print("Terminal 1 (PowerShell):")
    for key,value in {**SAFE_ENV,'DATABASE_URL':args.database_url or 'sqlite:///./kosh_work.db','DEV_LOGIN_ENABLED':'true'}.items():
        print(f"$env:{key} = '{value}'")
    print(r".\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010")
    print("Terminal 2: cd frontend; npm run dev -- --host 127.0.0.1 --port 5180")
    print("Open http://127.0.0.1:5180/login; use local sign-in with any email. The business dashboard opens with Meenakshi selected.")


if __name__=='__main__': main()
