"""Engine / session factory. Swap DATABASE_URL to move to PostgreSQL."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.pool import QueuePool
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import PROJECT_ROOT, Settings, get_settings


def build_engine(database_url: str, *, read_only: bool | None = None) -> Engine:
    """Create an engine.

    read_only=True (APP_STARTUP_MODE=verify): SQLite is opened with mode=ro and
    PRAGMA query_only, so any write fails at the database level. No directories
    are created and the journal mode is never changed. The file must already exist.
    """
    is_sqlite = database_url.startswith("sqlite")
    if read_only is None:
        # Fail closed: in verify mode every engine is read-only unless a caller opts out.
        read_only = get_settings().app_startup_mode == "verify"
    if read_only:
        if not is_sqlite:
            raise ValueError("read-only engines are supported for SQLite only")
        db_path = database_url.split("sqlite:///", 1)[-1]
        if not db_path or db_path == ":memory:":
            raise ValueError("read-only engines need a file-backed SQLite database")
        file_path = Path(db_path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"read-only verify: database file not found: {file_path}")
        uri = file_path.as_uri() + "?mode=ro"

        def _connect():
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=30)
            conn.execute("PRAGMA query_only = ON")
            return conn

        return create_engine("sqlite://", creator=_connect, poolclass=QueuePool, future=True)

    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        db_path = database_url.split("sqlite:///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, **kwargs)

    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            # Let SQLAlchemy own transaction boundaries so SAVEPOINTs
            # (per-tender isolation in upserts) work with pysqlite.
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if database_url not in ("sqlite://", "sqlite:///:memory:"):
                cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn):  # pragma: no cover - trivial
            conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.get_execution_options().get("sqlite_write_intent") else "BEGIN")

    return engine


def reserve_sqlite_writer(session: Session, *, renew_read: bool = False) -> None:
    """Reserve SQLite's writer before a bounded read/modify/write operation.

    Ordinary readers keep deferred transactions. A caller-owned transaction with
    pending ORM changes is preserved. Services that already commit may explicitly
    end a clean read snapshot before reserving; never hold this across HTTP/AI.
    """
    if session.get_bind().dialect.name != "sqlite":
        return
    if session.in_transaction():
        if not renew_read or session.new or session.dirty or session.deleted:
            return
        session.commit()
    session.connection(execution_options={"sqlite_write_intent": True})


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine((settings or get_settings()).resolved_database_url)
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _factory
    if _factory is None:
        _factory = build_session_factory(get_engine(settings))
    return _factory


def check_database(factory: sessionmaker[Session]) -> bool:
    try:
        with factory() as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def run_migrations(database_url: str) -> None:
    if get_settings().app_startup_mode == "verify":
        raise RuntimeError("Migrations are disabled while APP_STARTUP_MODE=verify")
    """Apply Alembic migrations up to head (used at startup and by the CLI)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def session_scope_dependency(factory: sessionmaker[Session]):
    def _get_db() -> Iterator[Session]:
        with factory() as session:
            yield session
    return _get_db


def check_schema_revision(database_url: str) -> None:
    """Read-only check that the database is at the code's Alembic head.

    Used when AUTO_MIGRATE=false. Never writes. Fails with the exact problem so
    a stale schema is caught at startup, not later as 'no such table'.
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()

    engine = build_engine(database_url, read_only=True)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()

    if current != head:
        raise RuntimeError(
            f"Database schema revision is {current!r} but this code needs {head!r}. "
            "Startup stopped because AUTO_MIGRATE=false. Back up the database, then apply "
            "migrations manually before starting the app."
        )
