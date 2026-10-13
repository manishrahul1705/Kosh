"""Stage 3A: document text / table / structure extraction.

All PDFs are generated locally by tests/pdf_factory.py - no live GeM, no real
tender files. Stage 2 rows/files are created the way Stage 2 stores them.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.database.models import (
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    DocumentVersion,
    ExtractionJob,
    Tender,
    TenderDocument,
)
from app.extraction import job_queue as xq
from app.extraction.constants import ErrorCode, ExtractionError, ExtractionJobReason
from app.extraction.headings import detect_headings, english_part, normalize_heading
from app.extraction.job_queue import backfill_extraction_jobs, enqueue_extraction
from app.extraction.job_worker import SKIP_BUSY, ExtractionJobWorker, compute_backoff
from app.extraction.normalize import meaningful_char_count, normalize_text, word_count
from app.extraction.ocr import BaseOCRProvider, get_ocr_provider
from app.extraction.pdf_parser import PdfPlumberParser, TextLine
from app.extraction.quality import PageQuality, classify
from app.extraction.service import ALREADY, ERROR, EXTRACTED, ExtractionService
from app.extraction.storage import resolve_source_path, sniff_file_type
from app.utils.dates import utcnow
from tests.pdf_factory import (
    CORRUPT_PDF,
    PdfBuilder,
    blank_pdf,
    encrypted_pdf,
    gem_like_pdf,
    scanned_pdf,
    text_pdf,
)

BID = "GEM/2026/B/8124821"


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------
class Clock:
    def __init__(self) -> None:
        self.now = utcnow()

    def __call__(self):
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def xsettings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={
        "document_storage_path": str(tmp_path / "tenders"),
        "extraction_max_attempts": 3,
        "extraction_retry_backoff_minutes": 5.0,
        "extraction_stale_running_minutes": 30,
        "extraction_min_page_chars": 20,
        "ocr_enabled": False,
    })


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(xsettings, session_factory, clock) -> ExtractionService:
    return ExtractionService(xsettings, session_factory, use_default_ocr=False, clock=clock)


@pytest.fixture
def worker(xsettings, session_factory, service, clock) -> ExtractionJobWorker:
    return ExtractionJobWorker(xsettings, session_factory, service, clock=clock, sleep=lambda s: None)


def fresh(db) -> None:
    db.commit()
    db.expire_all()


def store_version(db, xsettings, data: bytes, *, bid: str = BID, version_number: int = 1,
                  name: str = "GeM-Bidding-1.pdf", document: TenderDocument | None = None,
                  storage_path: str | None = None, validation_status: str = "VALID",
                  sha_override: str | None = None) -> DocumentVersion:
    """Create Tender/TenderDocument/DocumentVersion + file exactly like Stage 2 stores them."""
    if document is None:
        tender = db.scalar(select(Tender).where(Tender.bid_number == bid))
        if tender is None:
            tender = Tender(bid_number=bid, status="ONGOING", source_fingerprint="fp", first_seen_at=utcnow(),
                            last_seen_at=utcnow(), bid_type="BID")
            db.add(tender)
            db.flush()
        document = TenderDocument(tender_id=tender.id, document_key="main_bid", document_type="MAIN_BID",
                                  discovered_at=utcnow(), last_seen_at=utcnow())
        db.add(document)
        db.flush()
        tender_dir = bid.replace("/", "_")
    else:
        tender_dir = db.get(Tender, document.tender_id).bid_number.replace("/", "_")
    sha = hashlib.sha256(data).hexdigest()
    rel = storage_path or f"{tender_dir}/documents/main_bid/v{version_number}_{sha[:12]}_{name}"
    path = xsettings.resolved_document_storage_path / rel.replace("\\", "/")
    if storage_path is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    v = DocumentVersion(document_id=document.id, version_number=version_number, sha256=sha_override or sha,
                        file_size=len(data), storage_path=rel, extension="pdf", validation_status=validation_status)
    db.add(v)
    db.flush()
    document.current_version_id = v.id
    db.commit()
    return v


def counts(db) -> dict:
    fresh(db)
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m))
            for m in (DocumentExtraction, DocumentPage, DocumentTable, DocumentSection, ExtractionJob)}


def current(db, version_id) -> DocumentExtraction:
    fresh(db)
    return db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == version_id,
                                                      DocumentExtraction.is_current.is_(True)))


def pages_of(db, extraction_id) -> list[DocumentPage]:
    fresh(db)
    return list(db.scalars(select(DocumentPage).where(DocumentPage.extraction_id == extraction_id)
                           .order_by(DocumentPage.page_number)))


def job(db, job_id) -> ExtractionJob:
    fresh(db)
    return db.get(ExtractionJob, job_id)


def queue(db, version_id, **kw) -> ExtractionJob:
    fresh(db)  # end any old WAL read snapshot before writing (test-session hygiene)
    res = enqueue_extraction(db, version_id, kw.pop("reason", ExtractionJobReason.MANUAL), **kw)
    db.commit()
    return res.job


# ===========================================================================
# 1-6, 16. text extraction + persistence
# ===========================================================================
def test_native_multi_page_extraction_is_persisted_with_1_based_pages(db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf())
    out = service.extract_version(v.id)
    assert (out.outcome, out.status, out.quality_status) == (EXTRACTED, "SUCCESS", "GOOD")
    e = current(db, v.id)
    assert (e.page_count, e.pages_with_text, e.text_class, e.text_coverage_ratio) == (3, 3, "TEXT_NATIVE", 1.0)
    from app.extraction.constants import EXTRACTOR_VERSION
    assert (e.extractor_name, e.extractor_version) == ("pdfplumber", EXTRACTOR_VERSION)
    assert e.tender_id == db.get(TenderDocument, v.document_id).tender_id and e.document_id == v.document_id
    assert e.source_sha256 == v.sha256 and e.source_file_size == v.file_size and e.duration_ms is not None
    pages = pages_of(db, e.id)
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert all(p.document_version_id == v.id for p in pages)
    assert "Bid Number: GEM/2026/B/8124821" in pages[0].raw_text
    assert "Bid Number: GEM/2026/B/8124821" in pages[0].normalized_text
    assert "OPTION CLAUSE" in pages[1].normalized_text and "SCOPE OF WORK" in pages[2].normalized_text
    # faithful: amounts, percentages and dates are untouched
    assert "Rs. 25,000" in pages[0].normalized_text and "16-10-2026 21:00:00" in pages[0].normalized_text
    assert "25 percent" in pages[1].normalized_text and "Rs. 1,00,000" in pages[2].normalized_text


def test_word_and_character_counts(db, xsettings, service):
    v = store_version(db, xsettings, text_pdf([["alpha beta gamma delta epsilon zeta"], ["one two three four five"]]))
    e = service.extract_version(v.id)
    pages = pages_of(db, e.extraction_id)
    assert [p.word_count for p in pages] == [6, 5]
    assert [p.char_count for p in pages] == [len("alpha beta gamma delta epsilon zeta"), len("one two three four five")]
    stored = current(db, v.id)
    assert stored.total_words == 11 and stored.total_characters == sum(p.char_count for p in pages)


def test_raw_and_normalized_text_are_both_persisted_faithfully(db, xsettings, service):
    b = PdfBuilder()
    p = b.page()
    p.text(40, 40, "EMD\xa0Amount: Rs. 25,000 (5%) on 06-10-2026", size=10)
    p.text(40, 120, "ePBG 3.00% of contract value", size=10)
    v = store_version(db, xsettings, b.build())
    e = service.extract_version(v.id)
    page = pages_of(db, e.extraction_id)[0]
    assert page.raw_text and page.normalized_text
    assert page.normalized_text == "EMD Amount: Rs. 25,000 (5%) on 06-10-2026\nePBG 3.00% of contract value"
    assert normalize_text(page.raw_text) == page.normalized_text  # normalized is derived deterministically


def test_empty_page_inside_a_text_document(db, xsettings, service):
    b = PdfBuilder()
    b.page().text(40, 40, "This tender page has plenty of readable words in it.", size=10)
    b.page()  # blank separator page, no image
    v = store_version(db, xsettings, b.build())
    out = service.extract_version(v.id)
    pages = pages_of(db, out.extraction_id)
    assert [p.has_text for p in pages] == [True, False] and pages[1].char_count == 0
    e = current(db, v.id)
    assert (e.status, e.quality_status, e.text_class, e.pages_without_text) == ("SUCCESS", "GOOD", "TEXT_PARTIAL", 1)


# ===========================================================================
# 8-11. scanned / corrupt / missing / unsupported / password / hash
# ===========================================================================
def test_likely_scanned_pdf_is_ocr_required_not_success(db, xsettings, service):
    v = store_version(db, xsettings, scanned_pdf(3))
    out = service.extract_version(v.id)
    e = current(db, v.id)
    assert out.status == "OCR_REQUIRED" and e.quality_status == "OCR_REQUIRED" and e.text_class == "LIKELY_SCANNED"
    assert e.page_count == 3 and e.pages_with_text == 0 and e.images_found == 3 and e.error_code == "OCR_REQUIRED"
    assert len(pages_of(db, e.id)) == 3  # pages are still recorded (OCR-ready)


def test_all_blank_pdf_is_empty_and_ocr_required(db, xsettings, service):
    v = store_version(db, xsettings, blank_pdf(2))
    service.extract_version(v.id)
    e = current(db, v.id)
    assert (e.status, e.quality_status, e.text_class) == ("OCR_REQUIRED", "EMPTY", "EMPTY")


def test_corrupt_pdf_is_permanent_failure(db, xsettings, service):
    v = store_version(db, xsettings, CORRUPT_PDF)
    out = service.extract_version(v.id)
    e = current(db, v.id)
    assert out.outcome == EXTRACTED and (e.status, e.quality_status, e.error_code) == ("FAILED", "FAILED", "PDF_CORRUPT")
    assert e.page_count == 0 and counts(db)["document_pages"] == 0


def test_password_protected_pdf(db, xsettings, service):
    v = store_version(db, xsettings, encrypted_pdf())
    service.extract_version(v.id)
    assert current(db, v.id).error_code == "PASSWORD_PROTECTED"


def test_missing_file_is_retryable_and_not_persisted(db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf())
    (xsettings.resolved_document_storage_path / v.storage_path).unlink()
    out = service.extract_version(v.id)
    assert (out.outcome, out.error_code, out.retryable) == (ERROR, "FILE_MISSING", True)
    assert counts(db)["document_extractions"] == 0


def test_unsupported_file_type(db, xsettings, service):
    v = store_version(db, xsettings, b"PK\x03\x04 this is a docx/zip archive", name="spec.docx")
    out = service.extract_version(v.id)
    e = current(db, v.id)
    assert out.status == "UNSUPPORTED" and (e.quality_status, e.error_code) == ("UNSUPPORTED", "UNSUPPORTED_FILE_TYPE")


def test_hash_mismatch_is_detected_and_file_untouched(db, xsettings, service):
    data = gem_like_pdf()
    v = store_version(db, xsettings, data, sha_override="0" * 64)
    service.extract_version(v.id)
    assert current(db, v.id).error_code == "FILE_HASH_MISMATCH"
    assert (xsettings.resolved_document_storage_path / v.storage_path).read_bytes() == data


def test_version_not_valid_is_not_extracted(db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf(), validation_status="INVALID")
    out = service.extract_version(v.id)
    assert (out.outcome, out.error_code, out.retryable) == (ERROR, "VERSION_NOT_ELIGIBLE", False)
    assert enqueue_extraction(db, v.id, ExtractionJobReason.MANUAL).skipped_reason == "not_eligible"


# ===========================================================================
# 12-13. tables
# ===========================================================================
def test_tables_are_stored_structurally(db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf())
    out = service.extract_version(v.id)
    fresh(db)
    tables = db.scalars(select(DocumentTable).where(DocumentTable.extraction_id == out.extraction_id)
                        .order_by(DocumentTable.page_number, DocumentTable.table_index)).all()
    assert [(t.page_number, t.table_index) for t in tables] == [(1, 1), (1, 2), (2, 1), (2, 2)]
    emd = json.loads(tables[1].table_json)
    assert emd == [["EMD Amount", "Rs. 25,000"], ["ePBG Percentage(%)", "5.00"]]
    assert (tables[1].row_count, tables[1].column_count, tables[1].extraction_method) == (2, 2, "pdfplumber:lines")
    assert tables[1].table_text == "EMD Amount | Rs. 25,000\nePBG Percentage(%) | 5.00"
    assert json.loads(tables[3].table_json) == [["S.No.", "Consignee", "Quantity"], ["1", "Jalpaiguri", "2"]]
    assert all(t.document_version_id == v.id for t in tables)
    assert current(db, v.id).tables_found == 4


def test_multiple_tables_on_one_page(db, xsettings, service):
    b = PdfBuilder()
    p = b.page()
    bottom = p.table(40, 40, [200, 200], [["A1", "B1"], ["A2", "B2"]])
    bottom = p.table(40, bottom + 30, [100, 100, 100], [["x", "y", "z"]])
    p.table(40, bottom + 30, [150, 150], [["Delivery", "30 days"], ["Warranty", "1 year"], ["EMD", "No"]])
    v = store_version(db, xsettings, b.build())
    out = service.extract_version(v.id)
    fresh(db)
    tables = db.scalars(select(DocumentTable).where(DocumentTable.extraction_id == out.extraction_id)
                        .order_by(DocumentTable.table_index)).all()
    assert [(t.table_index, t.row_count, t.column_count) for t in tables] == [(1, 2, 2), (2, 1, 3), (3, 3, 2)]
    assert {t.page_number for t in tables} == {1}


def test_tables_can_be_disabled(db, xsettings, session_factory, clock):
    svc = ExtractionService(xsettings.model_copy(update={"extraction_tables_enabled": False}), session_factory,
                            use_default_ocr=False, clock=clock)
    v = store_version(db, xsettings, gem_like_pdf())
    assert svc.extract_version(v.id).tables_found == 0


# ===========================================================================
# 14. headings
# ===========================================================================
def test_headings_detected_in_document_order_with_traceability(db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf())
    out = service.extract_version(v.id)
    fresh(db)
    secs = db.scalars(select(DocumentSection).where(DocumentSection.extraction_id == out.extraction_id)
                      .order_by(DocumentSection.sequence)).all()
    got = [(s.sequence, s.page_number, s.normalized_heading, s.detection_method) for s in secs]
    assert got == [
        (1, 1, "bid document", "known_heading"),
        (2, 1, "bid details", "known_heading"),
        (3, 1, "emd detail", "known_heading"),
        (4, 2, "mse purchase preference", "known_heading"),
        (5, 2, "buyer added bid specific terms and conditions", "known_heading"),
        (6, 2, "generic", "numbered"),
        (7, 3, "scope of work", "known_heading"),
    ]
    # key/value line "Bid Number: GEM/..." and table row "MSE Purchase Preference | Yes" are NOT headings
    assert secs[0].heading_level == 1 and secs[1].heading_level == 2 and secs[5].heading == "1. Generic"
    page1 = pages_of(db, out.extraction_id)[0].normalized_text
    assert page1[secs[1].char_offset:].startswith("Bid Details")
    assert all(s.document_version_id == v.id for s in secs)


def _line(text, size=9.0, bold=0.0, in_table=False, page=1, top=10.0):
    return TextLine(page, text, top, 40.0, size, bold, in_table, len(text.split()))


def test_heading_rules_are_generic_and_conservative():
    lines = [
        _line("Annexure Payment Schedule", size=12.0, bold=1.0, top=10),        # font_size (unknown title)
        _line("ANNEXURE A", top=30),                                               # uppercase
        _line("Delivery Instructions", bold=1.0, top=50),                          # bold_line
        _line("2.1 Inspection Process", bold=1.0, top=70),                         # numbered, depth 2 -> level 3
        _line("Bid Number: GEM/2026/B/1", bold=1.0, top=90),                       # label: value -> no
        _line("and", bold=1.0, top=110),                                           # lowercase fragment -> no
        _line("Bid splitting not applied.", top=130),                              # sentence -> no
        _line("MSE Purchase Preference Yes", in_table=True, top=150),              # table row -> no
        _line("EMD Detail", in_table=True, top=170),                               # exact known title in table -> yes
        _line("The seller shall deliver the goods within thirty days of order.", top=190),
    ]
    got = [(h.normalized_heading, h.detection_method, h.heading_level) for h in detect_headings(lines, 9.0)]
    assert got == [
        ("annexure payment schedule", "font_size", 1),
        ("annexure a", "uppercase", 3),
        ("delivery instructions", "bold_line", 3),
        ("inspection process", "numbered", 3),
        ("emd detail", "known_heading", 2),
    ]


def test_bilingual_heading_uses_english_part():
    hindi = "\ufffdबड \ufffdववरण/ Bid Details"
    assert english_part(hindi) == "Bid Details" and normalize_heading(hindi) == "bid details"
    assert normalize_heading("3. Warranty") == "warranty"
    assert detect_headings([_line(hindi, bold=1.0)], 9.0)[0].heading == hindi


# ===========================================================================
# 15. quality formula + normalization units
# ===========================================================================
@pytest.mark.parametrize("pages,truncated,expected", [
    ([], False, ("FAILED", "FAILED")),
    ([PageQuality(True, 0, False)] * 3, False, ("SUCCESS", "GOOD")),
    ([PageQuality(True, 0, False), PageQuality(False, 0, False)], False, ("SUCCESS", "GOOD")),
    ([PageQuality(False, 1, False)] * 2, False, ("OCR_REQUIRED", "OCR_REQUIRED")),
    ([PageQuality(False, 0, False)] * 2, False, ("OCR_REQUIRED", "EMPTY")),
    ([PageQuality(True, 0, False), PageQuality(False, 1, False)], False, ("PARTIAL_SUCCESS", "PARTIAL")),
    ([PageQuality(True, 0, False), PageQuality(False, 1, False), PageQuality(False, 1, False)], False,
     ("OCR_REQUIRED", "OCR_REQUIRED")),
    ([PageQuality(True, 0, False), PageQuality(False, 0, True)], False, ("PARTIAL_SUCCESS", "PARTIAL")),
    ([PageQuality(False, 0, True)] * 2, False, ("FAILED", "FAILED")),
    ([PageQuality(True, 0, False)], True, ("PARTIAL_SUCCESS", "PARTIAL")),
])
def test_quality_classification_formula(pages, truncated, expected):
    q = classify(pages, truncated)
    assert (q.status, q.quality) == expected


def test_normalization_is_conservative():
    raw = "Bid\u00a0Value:\t₹ 1,25,000.50  (18%)\r\n\r\n\r\n\r\nDate: 06-10-2026\u200b (cid:12)x\u00ad\nक्\u200dष"
    out = normalize_text(raw)
    assert out == "Bid Value: ₹ 1,25,000.50 (18%)\n\nDate: 06-10-2026 \ufffdx\nक्\u200dष"
    assert word_count(out) == 9 and meaningful_char_count("₹ 25,000 \ufffd") == 5
    assert normalize_text(None) == "" and normalize_text("  \n\n ") == ""


# ===========================================================================
# 17-20. idempotency, force, versions
# ===========================================================================
def test_same_version_twice_does_not_duplicate(db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf())
    first = service.extract_version(v.id)
    before = counts(db)
    second = service.extract_version(v.id)
    assert second.outcome == ALREADY and second.extraction_id == first.extraction_id
    assert counts(db) == before and before["document_pages"] == 3


def test_db_allows_only_one_current_extraction_per_version(db, xsettings, service, session_factory):
    v = store_version(db, xsettings, gem_like_pdf())
    service.extract_version(v.id)
    e = current(db, v.id)
    with session_factory() as s:
        s.add(DocumentExtraction(document_version_id=v.id, document_id=e.document_id, tender_id=e.tender_id,
                                 extractor_name="pdfplumber", extractor_version=e.extractor_version, status="SUCCESS",
                                 quality_status="GOOD", is_current=True))
        with pytest.raises(IntegrityError):
            s.commit()


def test_forced_reextraction_keeps_history(db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf())
    first = service.extract_version(v.id)
    second = service.extract_version(v.id, force=True)
    assert second.outcome == EXTRACTED and second.extraction_id != first.extraction_id
    fresh(db)
    old, new = db.get(DocumentExtraction, first.extraction_id), db.get(DocumentExtraction, second.extraction_id)
    assert (old.is_current, new.is_current) == (False, True)
    assert len(pages_of(db, old.id)) == len(pages_of(db, new.id)) == 3   # old pages kept as history
    assert current(db, v.id).id == new.id


def test_versions_are_extracted_independently(db, xsettings, service):
    v1 = store_version(db, xsettings, text_pdf([["Original tender wording for version one only."]]))
    doc = db.get(TenderDocument, v1.document_id)
    v2 = store_version(db, xsettings, text_pdf([["Corrigendum wording changed in version two now."]]),
                       document=doc, version_number=2)
    e1 = service.extract_version(v1.id)
    e2 = service.extract_version(v2.id)
    assert e1.extraction_id != e2.extraction_id
    assert "version one" in pages_of(db, e1.extraction_id)[0].normalized_text
    assert "version two" in pages_of(db, e2.extraction_id)[0].normalized_text
    assert current(db, v1.id).id == e1.extraction_id  # v1 never overwritten by v2


# ===========================================================================
# 21-26. jobs & worker
# ===========================================================================
def test_job_pending_running_success_with_atomic_finish(db, xsettings, session_factory, service, worker):
    v = store_version(db, xsettings, gem_like_pdf())
    j = queue(db, v.id)
    seen = {}
    original = service.prepare

    def spy(version_id, force=False):
        with session_factory() as other:  # claim is committed before parsing starts
            row = other.get(ExtractionJob, j.id)
            seen.update(status=row.status, locked_by=row.locked_by, attempt=row.attempt_count)
            other.execute(text("PRAGMA busy_timeout=200"))
            other.execute(text("UPDATE tenders SET title='write while parsing' WHERE id=1"))
            other.commit()  # no SQLite write lock is held during parsing
        return original(version_id, force)

    service.prepare = spy
    batch = worker.run_batch()
    assert seen == {"status": "RUNNING", "locked_by": worker.worker_id, "attempt": 1}
    r = batch.jobs[0]
    final = job(db, j.id)
    assert (r.status, final.status, final.outcome, final.locked_by) == ("SUCCESS", "SUCCESS", "SUCCESS", None)
    assert final.extraction_id == current(db, v.id).id and final.finished_at is not None


def test_ocr_required_job_lifecycle(db, xsettings, worker):
    v = store_version(db, xsettings, scanned_pdf(2))
    j = queue(db, v.id)
    worker.run_batch()
    final = job(db, j.id)
    assert (final.status, final.error_code, final.attempt_count) == ("OCR_REQUIRED", "OCR_REQUIRED", 1)
    assert worker.run_batch().processed == 0  # terminal: not retried


def test_failed_job_lifecycle_is_not_retried(db, xsettings, worker):
    v = store_version(db, xsettings, CORRUPT_PDF)
    j = queue(db, v.id)
    worker.run_batch()
    final = job(db, j.id)
    assert (final.status, final.error_code, final.next_retry_at) == ("FAILED", "PDF_CORRUPT", None)
    assert worker.run_batch().processed == 0


def test_missing_file_retries_with_backoff_then_fails(db, xsettings, worker, clock):
    v = store_version(db, xsettings, gem_like_pdf())
    (xsettings.resolved_document_storage_path / v.storage_path).unlink()
    j = queue(db, v.id)
    worker.run_batch()
    first = job(db, j.id)
    assert (first.status, first.error_code) == ("RETRY", "FILE_MISSING")
    assert first.next_retry_at == clock.now + timedelta(minutes=5)
    assert worker.run_batch().processed == 0          # next_retry_at respected
    clock.advance(minutes=6)
    worker.run_batch()
    assert job(db, j.id).next_retry_at == clock.now + timedelta(minutes=10)
    clock.advance(minutes=11)
    worker.run_batch()
    final = job(db, j.id)
    assert (final.status, final.error_code, final.attempt_count) == ("FAILED", "RETRIES_EXHAUSTED", 3)
    assert counts(db)["document_extractions"] == 0


def test_retry_succeeds_once_stage2_restores_the_file(db, xsettings, worker, clock):
    data = gem_like_pdf()
    v = store_version(db, xsettings, data)
    path = xsettings.resolved_document_storage_path / v.storage_path
    path.unlink()
    j = queue(db, v.id)
    worker.run_batch()
    path.write_bytes(data)                            # Stage 2 restoration
    clock.advance(minutes=6)
    worker.run_batch()
    assert job(db, j.id).status == "SUCCESS" and current(db, v.id).status == "SUCCESS"


def test_backoff_is_capped():
    s = Settings(_env_file=None, extraction_retry_backoff_minutes=60, extraction_retry_max_backoff_minutes=90)
    assert compute_backoff(1, s) == timedelta(minutes=60) and compute_backoff(4, s) == timedelta(minutes=90)


def test_worker_processes_single_job_and_bounded_batches(db, xsettings, worker):
    ids = [store_version(db, xsettings, text_pdf([[f"Tender {i} document text with enough words"]]),
                         bid=f"GEM/2026/B/90000{i}").id for i in range(3)]
    for vid in ids:
        queue(db, vid)
    assert worker.run_batch().processed == 1                  # default 1 job per run
    assert worker.run_batch(max_jobs=5).processed == 2        # bounded by what is due
    assert worker.run_batch(max_jobs=5).processed == 0
    assert counts(db)["document_extractions"] == 3


def test_already_extracted_job_is_skipped_but_forced_job_reextracts(db, xsettings, worker, service, session_factory):
    v = store_version(db, xsettings, gem_like_pdf())
    service.extract_version(v.id)
    assert enqueue_extraction(db, v.id, ExtractionJobReason.MANUAL).skipped_reason == "already_extracted"
    with session_factory() as s:  # a stale queued job (e.g. from before the extraction) is skipped
        s.add(ExtractionJob(document_version_id=v.id, status="PENDING", reason="BACKFILL",
                            created_at=utcnow(), updated_at=utcnow()))
        s.commit()
    r = worker.run_batch().jobs[0]
    assert (r.status, r.error_code) == ("SKIPPED", "ALREADY_EXTRACTED")
    forced = queue(db, v.id, reason=ExtractionJobReason.REEXTRACT, force=True)
    r2 = worker.run_batch().jobs[0]
    assert r2.job_id == forced.id and r2.status == "SUCCESS"
    fresh(db)
    assert db.scalar(select(func.count()).select_from(DocumentExtraction)) == 2


def test_force_upgrades_an_already_queued_job(db, xsettings):
    v = store_version(db, xsettings, gem_like_pdf())
    a = queue(db, v.id)
    res = enqueue_extraction(db, v.id, ExtractionJobReason.REEXTRACT, force=True)
    db.commit()
    assert not res.created and res.job_id == a.id and job(db, a.id).force is True
    assert job(db, a.id).reason == "REEXTRACT"


def test_stale_running_job_recovery_and_live_job_untouched(db, xsettings, worker, clock, session_factory):
    v1 = store_version(db, xsettings, gem_like_pdf(), bid="GEM/2026/B/1000001")
    v2 = store_version(db, xsettings, gem_like_pdf(), bid="GEM/2026/B/1000002")
    with session_factory() as s:
        s.add_all([
            ExtractionJob(id=50, document_version_id=v1.id, status="RUNNING", attempt_count=1, started_at=clock.now,
                          locked_by=f"{socket.gethostname()}:1:dead", created_at=utcnow(), updated_at=utcnow()),
            ExtractionJob(id=51, document_version_id=v2.id, status="RUNNING", attempt_count=1,
                          started_at=clock.now - timedelta(minutes=2), locked_by="other-host:9:live",
                          created_at=utcnow(), updated_at=utcnow()),
        ])
        s.commit()
    batch = worker.run_batch(max_jobs=5)
    assert batch.recovered_stale == 1
    assert (job(db, 50).status, job(db, 50).attempt_count) == ("SUCCESS", 2)
    assert job(db, 51).status == "RUNNING" and job(db, 51).locked_by == "other-host:9:live"


def test_extraction_workers_never_overlap(db, xsettings, worker, session_factory, service, clock):
    v = store_version(db, xsettings, gem_like_pdf())
    j = queue(db, v.id)
    other = ExtractionJobWorker(xsettings, session_factory, service, clock=clock)
    with worker.lock.acquire():
        assert other.run_batch().skipped_reason == SKIP_BUSY and worker.is_busy()
    assert job(db, j.id).status == "PENDING"


def test_ocr_provider_fills_text_for_scanned_pages(db, xsettings, session_factory, clock):
    class FakeOCR(BaseOCRProvider):
        name = "fake"

        def ocr_page(self, pdf_path, page_number):
            from app.extraction.ocr import OCRResult
            return OCRResult(f"Scanned annexure page {page_number} recognised by OCR engine",confidence=99)

    svc = ExtractionService(xsettings, session_factory, ocr_provider=FakeOCR(), clock=clock)
    v = store_version(db, xsettings, scanned_pdf(2))
    out = svc.extract_version(v.id)
    e = current(db, v.id)
    assert (out.status, e.pages_ocr, e.pages_with_text) == ("SUCCESS", 2, 2)
    assert {p.text_source for p in pages_of(db, e.id)} == {"OCR"}
    assert get_ocr_provider(xsettings) is None  # OFF by default


def test_page_level_parser_error_gives_partial_not_failure(db, xsettings, service, monkeypatch):
    original = PdfPlumberParser._parse_page

    def flaky(self, pdf, index):
        if index == 1:
            raise RuntimeError("synthetic page failure")
        return original(self, pdf, index)

    monkeypatch.setattr(PdfPlumberParser, "_parse_page", flaky)
    v = store_version(db, xsettings, gem_like_pdf())
    with pytest.raises(RuntimeError):
        service.extract_version(v.id)  # unexpected errors outside page parsing still surface ...
    monkeypatch.setattr(PdfPlumberParser, "_parse_page", original)

    def page_error(self, pdf, index):
        r = original(self, pdf, index)
        if index == 1:
            r.error_code, r.raw_text, r.tables, r.lines = "PARSER_ERROR", "", [], []
        return r

    monkeypatch.setattr(PdfPlumberParser, "_parse_page", page_error)
    service.extract_version(v.id)
    e = current(db, v.id)
    assert (e.status, e.quality_status, e.error_code) == ("PARTIAL_SUCCESS", "PARTIAL", "PAGE_ERRORS")
    assert [p.error_code for p in pages_of(db, e.id)] == [None, "PARSER_ERROR", None]


def test_worker_turns_unexpected_exception_into_retry(db, xsettings, worker, service):
    v = store_version(db, xsettings, gem_like_pdf())
    j = queue(db, v.id)

    def boom(version_id, force=False):
        raise RuntimeError("bug")

    service.prepare = boom
    worker.run_batch()
    assert (job(db, j.id).status, job(db, j.id).error_code) == ("RETRY", "WORKER_EXCEPTION")


def test_page_limit_marks_partial(db, xsettings, session_factory, clock):
    svc = ExtractionService(xsettings.model_copy(update={"extraction_max_pages": 2}), session_factory,
                            use_default_ocr=False, clock=clock)
    v = store_version(db, xsettings, gem_like_pdf())
    svc.extract_version(v.id)
    e = current(db, v.id)
    assert (e.page_count, e.status, e.error_code) == (2, "PARTIAL_SUCCESS", "PAGE_LIMIT")


# ===========================================================================
# 27-29. backfill
# ===========================================================================
def test_backfill_is_bounded_and_skips_extracted_and_active(db, xsettings, service):
    vs = [store_version(db, xsettings, text_pdf([[f"Backfill tender {i} has some text"]]), bid=f"GEM/2026/B/80000{i}")
          for i in range(5)]
    service.extract_version(vs[0].id)            # already extracted
    queue(db, vs[1].id)                           # active job
    store_version(db, xsettings, gem_like_pdf(), bid="GEM/2026/B/8000099", validation_status="INVALID")
    assert backfill_extraction_jobs(db, limit=2, dry_run=True) == [vs[4].id, vs[3].id]
    db.rollback()
    first = backfill_extraction_jobs(db, limit=2)
    db.commit()
    second = backfill_extraction_jobs(db, limit=2)
    db.commit()
    assert first == [vs[4].id, vs[3].id] and second == [vs[2].id]
    assert backfill_extraction_jobs(db, limit=2) == []
    fresh(db)
    per_version = db.execute(select(ExtractionJob.document_version_id, func.count())
                             .group_by(ExtractionJob.document_version_id)).all()
    assert all(n == 1 for _, n in per_version)


# ===========================================================================
# 30-37. API, health, stats
# ===========================================================================
@pytest.fixture
def api(settings, session_factory, source, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    s = settings.model_copy(update={"document_storage_path": str(tmp_path / "tenders")})
    app = create_app(s, session_factory=session_factory, collector_factory=source)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def authorized_api(api, session_factory):
    """Authorize the test client as a provisioned user holding TENDER_ANALYSIS_READ."""
    from uuid import uuid4
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from app.database.auth_models import AppUser
    from app.database.platform_auth_models import PlatformOperatorGrant

    subject = str(uuid4())
    with session_factory() as db:
        user = AppUser(supabase_user_id=subject)
        db.add(user)
        db.flush()
        db.add(PlatformOperatorGrant(user_id=user.id, granted_by_user_id=user.id,
                                     permission="TENDER_ANALYSIS_READ", status="ACTIVE"))
        db.commit()

    identity = AuthenticatedIdentity(
        subject=subject,
        email="extraction-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )
    api.app.dependency_overrides[get_current_user] = lambda: identity
    yield api
    api.app.dependency_overrides.clear()


def test_api_extraction_endpoints(authorized_api, db, xsettings, service):
    api = authorized_api
    v = store_version(db, xsettings, gem_like_pdf())
    ext_id = service.extract_version(v.id).extraction_id

    lst = api.get("/api/extractions", params={"page": 1, "page_size": 20})
    assert lst.status_code == 200, lst.text
    assert lst.json()["total"] == 1 and lst.json()["items"][0]["id"] == ext_id
    detail = api.get(f"/api/extractions/{ext_id}").json()
    assert detail["status"] == "SUCCESS" and detail["page_count"] == 3
    assert detail["source"] == {"tender_id": detail["tender_id"], "bid_number": BID, "document_id": v.document_id,
                                "document_type": "MAIN_BID", "document_key": "main_bid", "document_version_id": v.id,
                                "version_number": 1, "sha256": v.sha256}
    by_version = api.get(f"/api/extractions/document-version/{v.id}").json()
    assert by_version["current"]["id"] == ext_id and len(by_version["history"]) == 1

    pages = api.get(f"/api/extractions/{ext_id}/pages").json()
    assert [p["page_number"] for p in pages["items"]] == [1, 2, 3] and "normalized_text" not in pages["items"][0]
    page2 = api.get(f"/api/extractions/{ext_id}/pages/2").json()
    assert page2["page_number"] == 2 and "OPTION CLAUSE" in page2["normalized_text"] and page2["raw_text"]
    assert page2["source"]["version_number"] == 1
    assert api.get(f"/api/extractions/{ext_id}/pages/99").status_code == 404

    tables = api.get(f"/api/extractions/{ext_id}/tables", params={"page_number": 1}).json()["items"]
    assert [t["table_index"] for t in tables] == [1, 2] and tables[1]["rows"][0] == ["EMD Amount", "Rs. 25,000"]
    sections = api.get(f"/api/extractions/{ext_id}/sections").json()["items"]
    assert sections[1]["normalized_heading"] == "bid details" and sections[1]["page_number"] == 1

    assert api.get("/api/extractions/999999").status_code == 404
    assert api.get("/api/extractions/not-a-number").status_code == 422



@pytest.fixture
def authenticated_api(api, session_factory):
    """Verified document operator in the isolated test database."""
    from uuid import uuid4
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from app.database.auth_models import AppUser
    from app.database.platform_auth_models import PlatformOperatorGrant

    subject = str(uuid4())

    with session_factory() as db:
        user = AppUser(supabase_user_id=subject)
        db.add(user)
        db.flush()
        db.add(
            PlatformOperatorGrant(
                user_id=user.id,
                granted_by_user_id=user.id,
                permission="DOCUMENT_JOBS_MANAGE",
                status="ACTIVE",
            )
        )
        db.commit()

    identity = AuthenticatedIdentity(
        subject=subject,
        email="stage3a-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )
    api.app.dependency_overrides[get_current_user] = lambda: identity

    try:
        yield api
    finally:
        api.app.dependency_overrides.pop(get_current_user, None)


def test_api_queue_reextract_and_jobs(authenticated_api, db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf())
    q1 = authenticated_api.post(f"/api/extractions/document-version/{v.id}/queue").json()
    q2 = authenticated_api.post(f"/api/extractions/document-version/{v.id}/queue").json()
    assert q1["queued"] is True and q2 == {**q2, "queued": False, "reason": "already_queued", "job_id": q1["job_id"]}
    jobs = authenticated_api.get("/api/extractions/jobs", params={"page": 1, "page_size": 20})
    assert jobs.status_code == 200 and jobs.json()["total"] == 1
    assert authenticated_api.get(f"/api/extractions/jobs/{q1['job_id']}").json()["status"] == "PENDING"
    assert authenticated_api.get("/api/extractions/jobs/424242").status_code == 404
    re = authenticated_api.post(f"/api/extractions/document-version/{v.id}/reextract").json()
    assert re["job_id"] == q1["job_id"] and job(db, q1["job_id"]).force is True
    assert authenticated_api.post("/api/extractions/document-version/999999/queue").status_code == 404
    assert authenticated_api.get("/api/extractions/worker").json()["extraction_jobs_pending"] == 1


def test_no_static_get_route_is_swallowed_by_a_dynamic_route(authenticated_api):
    """Behavioural guard (independent of FastAPI routing internals): every static GET
    path in the OpenAPI schema must reach its own handler - never fail with a
    path-parameter validation error such as "jobs" is not an integer."""
    paths = [p for p, ops in authenticated_api.app.openapi()["paths"].items() if "{" not in p and "get" in ops]
    assert {"/api/extractions", "/api/extractions/jobs", "/api/extractions/worker",
            "/api/documents/jobs", "/api/documents/worker"} <= set(paths)
    for path in paths:
        r = authenticated_api.get(path)
        if r.status_code == 422:
            locs = [e.get("loc", [None])[0] for e in r.json().get("detail", [])]
            assert "path" not in locs, f"{path} was captured by a dynamic route: {r.text}"
    assert authenticated_api.get("/api/extractions/jobs", params={"page": 1, "page_size": 20}).status_code == 200
    assert authenticated_api.get("/api/documents/jobs", params={"page": 1, "page_size": 20}).status_code == 200


def test_health_and_stats_expose_stage3a(api, db, xsettings, service):
    v1 = store_version(db, xsettings, gem_like_pdf(), bid="GEM/2026/B/7000001")
    v2 = store_version(db, xsettings, scanned_pdf(1), bid="GEM/2026/B/7000002")
    store_version(db, xsettings, gem_like_pdf(), bid="GEM/2026/B/7000003")     # never queued
    service.extract_version(v1.id)
    service.extract_version(v2.id)
    v4 = store_version(db, xsettings, gem_like_pdf(), bid="GEM/2026/B/7000004")
    queue(db, v4.id)

    from tests.conftest import sign_in
    sign_in(api.app)
    s = api.get("/api/stats").json()
    api.app.dependency_overrides.clear()
    assert (s["extractions_total"], s["extractions_success"], s["extractions_ocr_required"]) == (2, 1, 1)
    assert (s["extraction_jobs_pending"], s["document_versions_without_extraction"]) == (1, 2)
    assert s["pages_extracted"] == 4 and s["tables_extracted"] == 4
    assert s["extraction"]["document_versions_unqueued"] == 1
    assert s["total_tenders"] == 4 and "document_worker" in s   # Stage 1/2 contract intact

    h = api.get("/health").json()
    assert h["status"] == "healthy" and h["extraction_worker"]["extraction_worker_enabled"] is False
    assert h["extraction_worker"]["extraction_scheduler_running"] is False
    assert h["extraction_worker"]["document_versions_unqueued"] == 1
    worker = api.app.state.extraction_worker
    with worker.lock.acquire():
        assert api.get("/health").json()["extraction_worker"]["extraction_worker_running"] is True


# ===========================================================================
# 38-39. safe paths
# ===========================================================================
def test_safe_path_resolution(tmp_path):
    root = tmp_path / "tenders"
    (root / "GEM_1" / "documents").mkdir(parents=True)
    f = root / "GEM_1" / "documents" / "a.pdf"
    f.write_bytes(b"%PDF-1.4")
    assert resolve_source_path(root, "GEM_1/documents/a.pdf") == f.resolve()
    assert resolve_source_path(root, "GEM_1\\documents\\a.pdf") == f.resolve()   # legacy Windows rows
    assert sniff_file_type(f) == "pdf"
    for bad in ("../outside.pdf", "GEM_1/../../outside.pdf", "/etc/passwd", "C:/Windows/win.ini",
                "\\\\server\\share\\x.pdf"):
        with pytest.raises(ExtractionError) as exc:
            resolve_source_path(root, bad)
        assert exc.value.code == "UNSAFE_PATH", bad
    with pytest.raises(ExtractionError) as exc:
        resolve_source_path(root, "GEM_1/documents/missing.pdf")
    assert exc.value.code == "FILE_MISSING" and exc.value.retryable


def test_symlink_escape_is_rejected(tmp_path):
    root = tmp_path / "tenders"
    root.mkdir()
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(b"%PDF-1.4 secret")
    try:
        os.symlink(outside, root / "link.pdf")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this system")
    with pytest.raises(ExtractionError) as exc:
        resolve_source_path(root, "link.pdf")
    assert exc.value.code == "UNSAFE_PATH"


def test_traversal_path_in_db_is_recorded_as_failure(db, xsettings, service):
    v = store_version(db, xsettings, gem_like_pdf(), storage_path="../../etc/passwd")
    out = service.extract_version(v.id)
    assert current(db, v.id).error_code == "UNSAFE_PATH" and out.status == "FAILED"


# ===========================================================================
# 40. scheduler
# ===========================================================================
def test_extraction_scheduler_disabled_by_default(settings, session_factory, source):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.scheduler.scheduler import EXTRACTION_WORKER_JOB_ID

    assert Settings(_env_file=None).extraction_worker_enabled is False
    base = {"scheduler_enabled": True, "collect_on_startup": False}
    app = create_app(settings.model_copy(update=base), session_factory=session_factory, collector_factory=source)
    with TestClient(app):
        assert app.state.scheduler._scheduler.get_job(EXTRACTION_WORKER_JOB_ID) is None
    on = settings.model_copy(update={**base, "extraction_worker_enabled": True, "extraction_job_poll_seconds": 45})
    app = create_app(on, session_factory=session_factory, collector_factory=source)
    with TestClient(app) as c:
        j = app.state.scheduler._scheduler.get_job(EXTRACTION_WORKER_JOB_ID)
        assert j.trigger.interval.total_seconds() == 45 and j.max_instances == 1 and j.coalesce
        assert c.get("/health").json()["extraction_worker"]["extraction_scheduler_running"] is True
    assert app.state.extraction_worker.stop_requested


# ===========================================================================
# 41-42. Stage 2 integration and integrity
# ===========================================================================
@pytest.fixture
def stage2(xsettings, db):
    from app.documents.documents_service import DocumentsService
    from tests.test_stage2a_idempotency import PDF_V1, SOURCE_URL, FakeGem

    gem = FakeGem()
    svc = DocumentsService(xsettings, transport=httpx.MockTransport(gem), sleep=lambda s: None)
    tender = Tender(bid_number="GEM/2026/B/8119946", title="t", status="ONGOING", source_fingerprint="fp",
                    first_seen_at=utcnow(), last_seen_at=utcnow(), source_internal_id="9988704", source_url=SOURCE_URL)
    db.add(tender)
    db.commit()
    return svc, gem, tender, PDF_V1


def test_new_stage2_version_queues_extraction_once(db, stage2):
    from tests.test_stage2a_idempotency import PDF_V2

    svc, gem, tender, _ = stage2
    r = svc.discover_and_download_tender_documents(db, tender.id)
    assert (r["downloaded"], r["failed"]) == (1, 0)
    fresh(db)
    jobs = db.scalars(select(ExtractionJob)).all()
    assert [(j.reason, j.status) for j in jobs] == [("NEW_VERSION", "PENDING")]
    svc.discover_and_download_tender_documents(db, tender.id)          # UNCHANGED -> no new job
    fresh(db)
    assert db.scalar(select(func.count()).select_from(ExtractionJob)) == 1
    gem.body = PDF_V2
    svc.discover_and_download_tender_documents(db, tender.id)          # v2 -> its own job
    fresh(db)
    assert sorted(db.scalars(select(ExtractionJob.document_version_id)).all()) == \
        sorted(db.scalars(select(DocumentVersion.id)).all())


def test_stage2_unaffected_when_extraction_enqueue_fails(db, stage2, monkeypatch, caplog, settings, session_factory):
    svc, _, tender, data = stage2

    def boom(*a, **k):
        raise RuntimeError("extraction queue down")

    monkeypatch.setattr(xq, "enqueue_extraction", boom)
    caplog.set_level("ERROR")
    r = svc.discover_and_download_tender_documents(db, tender.id)
    assert (r["status"], r["downloaded"], r["failed"]) == ("SUCCESS", 1, 0)
    fresh(db)
    v = db.scalar(select(DocumentVersion))
    assert v is not None and v.validation_status == "VALID"
    assert (svc.storage_root / v.storage_path).read_bytes() == data
    assert db.scalar(select(func.count()).select_from(ExtractionJob)) == 0
    assert any("extraction_job_queue_failed" in rec.getMessage() for rec in caplog.records)
    from app.services.extraction_status import extraction_status
    assert extraction_status(db)["document_versions_unqueued"] == 1      # visible -> backfill reconciles
    monkeypatch.undo()
    assert backfill_extraction_jobs(db, limit=5) == [v.id]


def test_auto_queue_can_be_disabled(db, xsettings, stage2):
    from app.documents.documents_service import DocumentsService

    _, gem, tender, _ = stage2
    import httpx as _httpx
    svc = DocumentsService(xsettings.model_copy(update={"extraction_auto_queue": False}),
                           transport=_httpx.MockTransport(gem), sleep=lambda s: None)
    svc.discover_and_download_tender_documents(db, tender.id)
    fresh(db)
    assert db.scalar(select(func.count()).select_from(ExtractionJob)) == 0


def test_extraction_never_modifies_stage2_rows_or_files(db, xsettings, worker, stage2):
    svc, gem, tender, _ = stage2
    gem.body = gem_like_pdf()  # a real, parseable PDF served by the fake GeM
    svc.discover_and_download_tender_documents(db, tender.id)
    fresh(db)
    v = db.scalar(select(DocumentVersion))
    doc = db.get(TenderDocument, v.document_id)
    path = svc.storage_root / v.storage_path
    snapshot = (v.sha256, v.version_number, v.storage_path, v.file_size, v.validation_status,
                doc.current_version_id, path.read_bytes(), path.stat().st_mtime_ns)
    worker.run_batch()
    fresh(db)
    v2, doc2 = db.get(DocumentVersion, v.id), db.get(TenderDocument, doc.id)
    assert (v2.sha256, v2.version_number, v2.storage_path, v2.file_size, v2.validation_status,
            doc2.current_version_id, path.read_bytes(), path.stat().st_mtime_ns) == snapshot
    assert current(db, v.id).status == "SUCCESS"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == v.sha256
    assert ErrorCode.FILE_MISSING.value == "FILE_MISSING"
