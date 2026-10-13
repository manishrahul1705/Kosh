"""Read-only schema revision check used when AUTO_MIGRATE=false.

Works only on disposable databases built by the migrations, or empty temp files.
data/gem.db is never opened.
"""

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT, get_settings
from app.database.session import check_schema_revision
from app.main import create_app

from tests.conftest import make_head_db
STALE = "0016_platform_operator_permissions"


def _head() -> str:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


HEAD = _head()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _url(path: Path) -> str:
    return "sqlite:///" + path.as_posix()


def _set_revision(path: Path, revision: str) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute("UPDATE alembic_version SET version_num = ?", (revision,))
        con.commit()
    finally:
        con.close()


def _startup_error_text(exc_info) -> str:
    parts = [str(exc_info.value)]
    parts += [str(e) for e in getattr(exc_info.value, "exceptions", [])]
    return " ".join(parts)


@pytest.fixture
def copy_at_head(tmp_path):
    db = tmp_path / "head.db"
    make_head_db(db)
    return db


@pytest.fixture
def copy_stale(tmp_path):
    db = tmp_path / "stale.db"
    make_head_db(db)
    _set_revision(db, STALE)
    return db


@pytest.fixture
def app_settings():
    return get_settings().model_copy(update={
        "app_startup_mode": "normal",
        "auto_migrate": False,
        "scheduler_enabled": False,
        "collect_on_startup": False,
        "startup_recovery_enabled": False,
        "document_worker_enabled": False,
        "extraction_worker_enabled": False,
        "field_extraction_worker_enabled": False,
        "ai_analysis_worker_enabled": False,
    })


def test_head_database_passes_and_is_unchanged(copy_at_head):
    before = _sha(copy_at_head)
    check_schema_revision(_url(copy_at_head))
    assert _sha(copy_at_head) == before


def test_stale_revision_is_refused_and_names_both_revisions(copy_stale):
    before = _sha(copy_stale)
    with pytest.raises(RuntimeError) as exc:
        check_schema_revision(_url(copy_stale))
    assert STALE in str(exc.value)
    assert HEAD in str(exc.value)
    assert _sha(copy_stale) == before


def test_empty_database_is_refused(tmp_path):
    db = tmp_path / "empty.db"
    db.touch()
    with pytest.raises(RuntimeError, match="None"):
        check_schema_revision(_url(db))


def test_missing_database_raises_and_is_not_created(tmp_path):
    db = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        check_schema_revision(_url(db))
    assert not db.exists()


def test_startup_refuses_stale_database(app_settings, copy_stale):
    settings = app_settings.model_copy(update={"database_url": _url(copy_stale)})
    before = _sha(copy_stale)
    app = create_app(settings)
    with pytest.raises(Exception) as exc:
        with TestClient(app):
            pass
    assert "schema revision" in _startup_error_text(exc)
    assert _sha(copy_stale) == before


def test_startup_with_head_database_serves_health(app_settings, copy_at_head):
    # Temporary copy only. The app may set WAL mode on this copy's first connection.
    settings = app_settings.model_copy(update={"database_url": _url(copy_at_head)})
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200