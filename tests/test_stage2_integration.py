"""Integration tests: Stage 1 → Stage 2 automation.

Verify that when Stage 1 discovers a NEW tender, Stage 2 automatically
creates a PENDING DocumentJob for it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import DocumentJob, Tender
from app.schemas.tender import TenderRecord
from app.services.tender_service import upsert_record
from app.utils.dates import utcnow


@pytest.fixture
def sample_record() -> TenderRecord:
    """Create a sample tender record for testing."""
    from app.core.constants import TenderStatus
    return TenderRecord(
        bid_number="GEM/2026/B/9999888",
        title="Test Tender for Stage 2 Integration",
        status=TenderStatus.ONGOING,
        category="Test",
        buyer_name="Test Buyer",
        bid_type="BID",
        bid_end_at=utcnow(),
        published_at=utcnow(),
        source_internal_id="test_b_id_123",
    )


def test_new_tender_creates_document_job(db: Session, sample_record: TenderRecord):
    """When Stage 1 creates a NEW tender, Stage 2 DocumentJob should be auto-created."""
    now = utcnow()

    # Stage 1: Discover and insert new tender
    result = upsert_record(db, sample_record, now=now, run_id=None)
    db.commit()

    # Verify tender was created
    tender = db.scalar(select(Tender).where(Tender.bid_number == sample_record.bid_number))
    assert tender is not None
    assert tender.id is not None

    # Stage 2: Verify DocumentJob was automatically created
    job = db.scalar(
        select(DocumentJob).where(DocumentJob.tender_id == tender.id)
    )
    assert job is not None
    assert job.status == "PENDING"
    assert job.attempt_count == 0
    assert job.started_at is None
    assert job.finished_at is None

    print(f"✓ New tender {tender.bid_number} auto-created DocumentJob {job.id}")


def test_existing_tender_update_does_not_duplicate_job(db: Session, sample_record: TenderRecord):
    """Updating an existing tender should not create duplicate DocumentJobs."""
    from app.core.constants import TenderStatus
    now = utcnow()

    # First discovery (creates tender and job)
    upsert_record(db, sample_record, now=now, run_id=None)
    db.commit()

    tender = db.scalar(select(Tender).where(Tender.bid_number == sample_record.bid_number))
    jobs_count_1 = db.scalar(
        select(len(tender.document_jobs))
    )
    assert jobs_count_1 == 1

    # Update the tender (create new record with changed title)
    updated_record = TenderRecord(
        bid_number=sample_record.bid_number,
        title="Updated Title",
        status=TenderStatus.ONGOING,
        category="Test",
        buyer_name="Test Buyer",
        bid_type="BID",
        bid_end_at=utcnow(),
        published_at=utcnow(),
        source_internal_id="test_b_id_123",
    )
    upsert_record(db, updated_record, now=now, run_id=None)
    db.commit()

    # Verify no new job was created
    tender_updated = db.scalar(select(Tender).where(Tender.bid_number == sample_record.bid_number))
    jobs_count_2 = db.scalar(
        select(len(tender_updated.document_jobs))
    )
    assert jobs_count_2 == 1
    print(f"✓ Updated tender {tender_updated.bid_number} did not create duplicate job")
