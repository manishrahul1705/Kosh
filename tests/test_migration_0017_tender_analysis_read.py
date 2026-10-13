"""Upgrade and downgrade tests for 0017_tender_analysis_read_permission (disposable SQLite only)."""

from uuid import uuid4

import pytest
from alembic import command
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.auth_models import AppUser
from app.database.platform_auth_models import PlatformOperatorGrant
from tests.test_stage2b_migration_cli import alembic_cfg


PREVIOUS = "0016_platform_operator_permissions"
TARGET = "0017_tender_analysis_read_permission"


@pytest.fixture
def migration_db(tmp_path):
    db_path = tmp_path / "migration_0017.db"
    cfg = alembic_cfg(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        yield cfg, engine, sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _current(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _insert_grant(factory, permission):
    with factory() as db:
        user = AppUser(supabase_user_id=str(uuid4()))
        admin = AppUser(supabase_user_id=str(uuid4()))
        db.add_all([user, admin])
        db.flush()
        db.add(
            PlatformOperatorGrant(
                user_id=user.id,
                permission=permission,
                status="ACTIVE",
                granted_by_user_id=admin.id,
            )
        )
        db.commit()


def test_upgrade_rejects_read_permission_before_0017(migration_db):
    cfg, engine, factory = migration_db
    command.upgrade(cfg, PREVIOUS)
    assert _current(engine) == PREVIOUS

    _insert_grant(factory, "DOCUMENT_JOBS_MANAGE")  # existing permission still accepted

    with pytest.raises(IntegrityError):
        _insert_grant(factory, "TENDER_ANALYSIS_READ")


def test_upgrade_accepts_read_permission_and_still_rejects_unknown(migration_db):
    cfg, engine, factory = migration_db
    command.upgrade(cfg, PREVIOUS)
    command.upgrade(cfg, TARGET)
    assert _current(engine) == TARGET

    _insert_grant(factory, "TENDER_ANALYSIS_READ")

    with pytest.raises(IntegrityError):
        _insert_grant(factory, "NOT_A_REAL_PERMISSION")


def test_downgrade_refused_while_read_grants_exist(migration_db):
    cfg, engine, factory = migration_db
    command.upgrade(cfg, TARGET)
    _insert_grant(factory, "TENDER_ANALYSIS_READ")

    with pytest.raises(RuntimeError, match="tender-analysis read grants exist"):
        command.downgrade(cfg, PREVIOUS)

    assert _current(engine) == TARGET
    with factory() as db:
        remaining = (
            db.query(PlatformOperatorGrant)
            .filter_by(permission="TENDER_ANALYSIS_READ")
            .count()
        )
    assert remaining == 1


def test_downgrade_succeeds_after_read_grants_removed(migration_db):
    cfg, engine, factory = migration_db
    command.upgrade(cfg, TARGET)
    _insert_grant(factory, "TENDER_ANALYSIS_READ")

    with factory() as db:
        db.query(PlatformOperatorGrant).filter_by(
            permission="TENDER_ANALYSIS_READ"
        ).delete(synchronize_session=False)
        db.commit()

    command.downgrade(cfg, PREVIOUS)
    assert _current(engine) == PREVIOUS

    with pytest.raises(IntegrityError):
        _insert_grant(factory, "TENDER_ANALYSIS_READ")

    command.upgrade(cfg, TARGET)
    assert _current(engine) == TARGET
