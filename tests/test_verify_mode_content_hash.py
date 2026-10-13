"""Verify-mode startup must leave database contents unchanged. Disposable databases only."""

import hashlib
import shutil
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT, get_settings
from app.main import create_app

from tests.conftest import make_head_db


def _content_digest(path: Path) -> str:
    """Hash logical table contents. File bytes can change from WAL bookkeeping alone."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        h = hashlib.sha256()
        tables = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        for t in tables:
            h.update(t.encode())
            for row in con.execute(f'select * from "{t}" order by 1'):
                h.update(repr(row).encode())
        return h.hexdigest()
    finally:
        con.close()


def test_verify_startup_leaves_contents_unchanged(tmp_path):
    db = tmp_path / "verify.db"
    make_head_db(db)
    before = _content_digest(db)

    settings = get_settings().model_copy(update={
        "database_url": f"sqlite:///{db.as_posix()}",
        "app_startup_mode": "verify",
        "auto_migrate": False,
        "scheduler_enabled": False,
        "startup_recovery_enabled": False,
        "collect_on_startup": False,
        "document_worker_enabled": False,
        "extraction_worker_enabled": False,
        "field_extraction_worker_enabled": False,
        "ai_analysis_worker_enabled": False,
        "lock_file": str(tmp_path / "collection.lock"),
        "debug_dir": str(tmp_path / "debug"),
        "document_storage_path": str(tmp_path / "tenders"),
    })

    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200

    assert _content_digest(db) == before