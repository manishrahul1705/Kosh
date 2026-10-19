"""Development-only, cross-process serialized creation of the local workspace."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from filelock import FileLock
from sqlalchemy import inspect, select
from app.database.session import build_engine, build_session_factory, reserve_sqlite_writer


def bootstrap_workspace(settings):
    if (settings.app_env.strip().lower()=="production" or not settings.kosh_auto_bootstrap
            or settings.app_startup_mode=="verify"):
        return False
    url=settings.resolved_database_url
    if not url.startswith("sqlite:///") or url.endswith(":memory:"):
        return False
    path=Path(url[len("sqlite:///"):]).resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    # The same FileLock primitive used by existing workers covers the entire
    # multi-transaction seed. The SQLite writer reservation serializes the
    # readiness check with other database writers; the file lock spans commits.
    with FileLock(str(path)+".bootstrap.lock", timeout=900):
        engine=build_engine(url)
        try:
            with build_session_factory(engine)() as db:
                reserve_sqlite_writer(db)
                if inspect(db.connection()).has_table("sellers"):
                    from app.database.models import Seller
                    if db.scalar(select(Seller.id).where(Seller.name=="Meenakshi Precision Components")):
                        return False
        finally:
            engine.dispose()
        from scripts.kosh_setup import setup
        with redirect_stdout(StringIO()):
            setup(url,root=path.parent/".kosh_bootstrap",configure_env=False,
                  public_storage=settings.resolved_document_storage_path)
        print("Kosh workspace ready: Meenakshi Precision Components",flush=True)
        return True
