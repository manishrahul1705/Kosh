"""Explicit SQLite WAL concurrency and snapshot-upgrade recovery evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
from sqlalchemy import select, update, text
from sqlalchemy.exc import OperationalError
from app.database.models import Tender
from tests.matching_factories import make_tender


def test_wal_readers_continue_during_committed_writer(db, session_factory):
    tender = make_tender(db, bid="GEM/2026/B/9700001")
    with session_factory() as reader:
        old = reader.scalar(select(Tender.title).where(Tender.id == tender.id))
        with session_factory() as writer:
            writer.execute(update(Tender).where(Tender.id == tender.id).values(title="new title"))
            writer.commit()
        assert reader.scalar(select(Tender.title).where(Tender.id == tender.id)) == old
        reader.rollback()
        assert reader.scalar(select(Tender.title).where(Tender.id == tender.id)) == "new title"
        assert reader.scalar(text("PRAGMA journal_mode")) == "wal"
        assert reader.scalar(text("PRAGMA busy_timeout")) == 30000


def test_snapshot_upgrade_lock_is_reproduced_then_recovered(db, session_factory, tmp_path):
    tender = make_tender(db, bid="GEM/2026/B/9700002")
    with session_factory() as stale:
        stale.scalar(select(Tender.title).where(Tender.id == tender.id))
        with session_factory() as writer:
            writer.execute(update(Tender).where(Tender.id == tender.id).values(title="scheduler commit"))
            writer.commit()
        try:
            stale.execute(update(Tender).where(Tender.id == tender.id).values(title="CLI stale snapshot"))
            stale.commit()
        except OperationalError as error:
            evidence = {"error": str(error.orig), "sqlite_errorcode": error.orig.sqlite_errorcode,
                        "sqlite_errorname": error.orig.sqlite_errorname}
            (tmp_path / "snapshot-lock.json").write_text(json.dumps(evidence))
            assert error.orig.sqlite_errorname == "SQLITE_BUSY_SNAPSHOT"
            stale.rollback()
        else:
            raise AssertionError("Expected a WAL stale-snapshot write failure")
        stale.execute(update(Tender).where(Tender.id == tender.id).values(title="fresh CLI retry"))
        stale.commit()
    with session_factory() as check:
        assert check.scalar(select(Tender.title).where(Tender.id == tender.id)) == "fresh CLI retry"
        assert check.execute(text("PRAGMA integrity_check")).scalars().all() == ["ok"]
        assert check.execute(text("PRAGMA foreign_key_check")).all() == []


def test_multiple_readers_and_competing_fresh_writers(db, session_factory):
    tender = make_tender(db, bid="GEM/2026/B/9700003")
    def writer(index):
        for sequence in range(15):
            with session_factory() as s:
                # A fresh write transaction can wait for the other writer; no prior read snapshot.
                s.execute(update(Tender).where(Tender.id == tender.id).values(title=f"{index}:{sequence}"))
                s.commit()
        return 15
    def reader(_):
        for _ in range(40):
            with session_factory() as s:
                assert s.scalar(select(Tender.id).where(Tender.id == tender.id)) == tender.id
        return 40
    with ThreadPoolExecutor(max_workers=6) as pool:
        writing = [pool.submit(writer, i) for i in range(2)]
        reading = [pool.submit(reader, i) for i in range(4)]
        writes = [f.result() for f in writing]
        reads = [f.result() for f in reading]
    assert sum(writes) == 30 and sum(reads) == 160
    assert db.execute(text("PRAGMA integrity_check")).scalars().all() == ["ok"]


def test_writer_reservation_avoids_snapshot_upgrade_with_reader(db, session_factory):
    from app.database.session import reserve_sqlite_writer
    tender = make_tender(db, bid="GEM/2026/B/9700004")
    with session_factory() as reserved:
        reserve_sqlite_writer(reserved)
        original = reserved.scalar(select(Tender.title).where(Tender.id == tender.id))
        with session_factory() as reader:
            assert reader.scalar(select(Tender.title).where(Tender.id == tender.id)) == original
        reserved.execute(update(Tender).where(Tender.id == tender.id).values(title="reserved writer"))
        reserved.commit()
    assert db.scalar(select(Tender.title).where(Tender.id == tender.id)) == "reserved writer"
