"""Stage 2A reliability regression tests.

Reproduce the real Windows bug (WinError 183: the second acquisition of an
identical GeM PDF tried to rename a fixed ``.tmp_<name>`` onto the already
existing final file) and cover the retry / failure-accounting behaviour.

No live GeM access: all HTTP is served by ``httpx.MockTransport``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.models import DocumentEvent, DocumentVersion, Tender, TenderDocument
from app.documents.downloader import (
    BlockedDownloadError,
    DocumentDownloader,
    DownloadedFile,
    FileTooLargeError,
    InvalidFileError,
    TransientDownloadError,
    URLValidationError,
)
from app.documents.documents_service import DocumentsService
from app.documents.manifest import generate_manifest, write_manifest
from app.utils.dates import utcnow

BID = "GEM/2026/B/8119946"
SOURCE_URL = "https://bidplus.gem.gov.in/showbidDocument/9988704"
PDF_V1 = b"%PDF-1.4\nfirst version of the GeM bid\n%%EOF\n"
PDF_V2 = b"%PDF-1.4\nSECOND version of the GeM bid (corrigendum)\n%%EOF\n"
LEGACY_NAME = "GeM-Bidding-9988704.pdf"


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------
def pdf_response(body: bytes = PDF_V1) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={
            "content-type": "application/pdf",
            "content-disposition": f'inline; filename="{LEGACY_NAME}"',
        },
    )


class FakeGem:
    """Scriptable fake of GeM /showbidDocument/{id}. Records every request."""

    def __init__(self, body: bytes = PDF_V1) -> None:
        self.body = body
        self.requests: list[httpx.Request] = []
        self.script: list = []  # one item consumed per request: Exception | httpx.Response

    @property
    def calls(self) -> int:
        return len(self.requests)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return pdf_response(self.body)


@pytest.fixture
def doc_settings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(
        update={
            "document_storage_path": str(tmp_path / "tenders"),
            "document_max_retries": 3,
            "backoff_base_seconds": 1.0,
            "max_retry_after_seconds": 300.0,
        }
    )


@pytest.fixture
def gem() -> FakeGem:
    return FakeGem()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def service(doc_settings: Settings, gem: FakeGem, sleeps: list[float]) -> DocumentsService:
    return DocumentsService(doc_settings, transport=httpx.MockTransport(gem), sleep=sleeps.append)


@pytest.fixture
def tender(db: Session) -> Tender:
    t = Tender(
        bid_number=BID,
        title="ONLINE UPS 3 KVA MICROTEK,1 KVA UPS MICROTEK",
        status="ONGOING",
        source_fingerprint="fp",
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
        source_internal_id="9988704",
        source_url=SOURCE_URL,
    )
    db.add(t)
    db.commit()
    return t


def storage(settings: Settings) -> Path:
    return settings.resolved_document_storage_path


def main_bid_dir(settings: Settings) -> Path:
    return storage(settings) / "GEM_2026_B_8119946" / "documents" / "main_bid"


def stored_files(settings: Settings) -> list[Path]:
    d = main_bid_dir(settings)
    return sorted(p for p in d.iterdir() if p.is_file()) if d.exists() else []


def temp_files(settings: Settings) -> list[Path]:
    root = storage(settings)
    return list(root.rglob(".tmp_*")) if root.exists() else []


def counts(db: Session) -> tuple[int, int]:
    db.expire_all()
    return db.query(TenderDocument).count(), db.query(DocumentVersion).count()


def run(service: DocumentsService, db: Session, tender: Tender) -> dict:
    return service.discover_and_download_tender_documents(db, tender.id)


def sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 1. first acquisition
# ---------------------------------------------------------------------------
def test_first_acquisition_creates_v1_and_fetches_pdf_only_once(service, db, tender, gem, doc_settings):
    r = run(service, db, tender)

    assert (r["discovered"], r["downloaded"], r["unchanged"], r["failed"]) == (1, 1, 0, 0)
    assert r["status"] == "SUCCESS"
    assert r["outcome"] == "SUCCESS_WITH_DOCUMENTS"
    assert counts(db) == (1, 1)
    assert gem.calls == 1, "direct PDF must not be requested twice"

    files = stored_files(doc_settings)
    assert [f.name for f in files] == [f"v1_{sha12(PDF_V1)}_{LEGACY_NAME}"]
    assert files[0].read_bytes() == PDF_V1
    assert temp_files(doc_settings) == []

    ver = db.query(DocumentVersion).one()
    assert ver.version_number == 1 and ver.sha256 == hashlib.sha256(PDF_V1).hexdigest()
    assert (storage(doc_settings) / ver.storage_path).read_bytes() == PDF_V1
    doc = db.query(TenderDocument).one()
    assert doc.current_version_id == ver.id and doc.document_type == "MAIN_BID"


# ---------------------------------------------------------------------------
# 2 / 3 / 5. identical bytes -> UNCHANGED (the WinError 183 scenario)
# ---------------------------------------------------------------------------
def test_second_identical_acquisition_is_unchanged(service, db, tender, doc_settings):
    run(service, db, tender)
    before = {p.name: p.read_bytes() for p in stored_files(doc_settings)}

    r = run(service, db, tender)

    assert (r["discovered"], r["downloaded"], r["unchanged"], r["failed"]) == (1, 0, 1, 0)
    assert r["status"] == "SUCCESS" and r["errors"] == []
    assert counts(db) == (1, 1)
    assert {p.name: p.read_bytes() for p in stored_files(doc_settings)} == before
    assert temp_files(doc_settings) == []
    events = [e.event_type for e in db.query(DocumentEvent).order_by(DocumentEvent.id)]
    assert events.count("UNCHANGED") == 1 and events.count("DOWNLOADED") == 1


def test_existing_destination_filename_does_not_raise_file_exists(service, db, tender, doc_settings):
    """Pre-existing GeM-Bidding-9988704.pdf (legacy v1 layout) must never cause a rename collision."""
    run(service, db, tender)
    # Recreate the exact legacy layout: final file has the plain Content-Disposition name.
    ver = db.query(DocumentVersion).one()
    current = storage(doc_settings) / ver.storage_path
    legacy = current.parent / LEGACY_NAME
    current.rename(legacy)
    ver.storage_path = "GEM_2026_B_8119946\\documents\\main_bid\\" + LEGACY_NAME  # Windows-style, as stored before
    db.commit()

    r = run(service, db, tender)  # previously: [WinError 183]

    assert (r["downloaded"], r["unchanged"], r["failed"]) == (0, 1, 0)
    assert [p.name for p in stored_files(doc_settings)] == [LEGACY_NAME]
    assert legacy.read_bytes() == PDF_V1
    assert counts(db) == (1, 1)


def test_repeat_identical_acquisition_five_times_keeps_one_version(service, db, tender, doc_settings):
    run(service, db, tender)
    for _ in range(5):
        r = run(service, db, tender)
        assert (r["downloaded"], r["unchanged"], r["failed"]) == (0, 1, 0)
    assert counts(db) == (1, 1)
    assert len(stored_files(doc_settings)) == 1
    assert temp_files(doc_settings) == []
    unchanged = db.query(DocumentEvent).filter_by(event_type="UNCHANGED").count()
    assert unchanged == 5


# ---------------------------------------------------------------------------
# 4. changed bytes -> v2, v1 preserved
# ---------------------------------------------------------------------------
def test_changed_bytes_create_v2_and_preserve_v1(service, db, tender, gem, doc_settings):
    run(service, db, tender)
    v1_path = stored_files(doc_settings)[0]

    gem.body = PDF_V2
    r = run(service, db, tender)

    assert (r["discovered"], r["downloaded"], r["unchanged"], r["failed"]) == (1, 1, 0, 0)
    assert counts(db) == (1, 2)
    assert v1_path.exists() and v1_path.read_bytes() == PDF_V1
    names = sorted(p.name for p in stored_files(doc_settings))
    assert names == sorted([f"v1_{sha12(PDF_V1)}_{LEGACY_NAME}", f"v2_{sha12(PDF_V2)}_{LEGACY_NAME}"])

    doc = db.query(TenderDocument).one()
    versions = {v.version_number: v for v in db.query(DocumentVersion)}
    assert doc.current_version_id == versions[2].id
    assert (storage(doc_settings) / versions[2].storage_path).read_bytes() == PDF_V2
    assert (storage(doc_settings) / versions[1].storage_path).read_bytes() == PDF_V1
    updated = db.query(DocumentEvent).filter_by(event_type="UPDATED").one()
    assert updated.old_version_id == versions[1].id and updated.new_version_id == versions[2].id

    # and v2 is itself idempotent
    r = run(service, db, tender)
    assert (r["downloaded"], r["unchanged"]) == (0, 1)
    assert counts(db) == (1, 2)


# ---------------------------------------------------------------------------
# 14. legacy v1 compatibility
# ---------------------------------------------------------------------------
def _make_legacy_state(service, db, tender, doc_settings) -> Path:
    run(service, db, tender)
    ver = db.query(DocumentVersion).one()
    new_style = storage(doc_settings) / ver.storage_path
    legacy = new_style.parent / LEGACY_NAME
    new_style.rename(legacy)
    ver.storage_path = "GEM_2026_B_8119946\\documents\\main_bid\\" + LEGACY_NAME
    db.commit()
    return legacy


def test_legacy_v1_then_changed_bytes_gets_v2_without_touching_legacy_file(service, db, tender, gem, doc_settings):
    legacy = _make_legacy_state(service, db, tender, doc_settings)
    gem.body = PDF_V2

    r = run(service, db, tender)

    assert (r["downloaded"], r["unchanged"], r["failed"]) == (1, 0, 0)
    assert legacy.read_bytes() == PDF_V1
    assert (legacy.parent / f"v2_{sha12(PDF_V2)}_{LEGACY_NAME}").read_bytes() == PDF_V2
    assert counts(db) == (1, 2)


def test_legacy_missing_file_is_restored_not_versioned(service, db, tender, doc_settings):
    legacy = _make_legacy_state(service, db, tender, doc_settings)
    legacy.unlink()  # user lost the file; DB still says v1

    r = run(service, db, tender)

    assert (r["downloaded"], r["unchanged"], r["failed"]) == (0, 1, 0)
    assert legacy.read_bytes() == PDF_V1  # restored at the recorded legacy path
    assert counts(db) == (1, 1)


# ---------------------------------------------------------------------------
# 6. unique temp files, cleanup
# ---------------------------------------------------------------------------
def test_temp_filenames_are_unique_per_acquisition(doc_settings, gem, tmp_path):
    dl = DocumentDownloader(doc_settings, transport=httpx.MockTransport(gem), sleep=lambda s: None)
    a = dl.fetch(SOURCE_URL, tmp_path / "in").file
    b = dl.fetch(SOURCE_URL, tmp_path / "in").file
    try:
        assert a.temp_path != b.temp_path
        assert a.temp_path.exists() and b.temp_path.exists()
        assert a.temp_path.name.startswith(".tmp_") and a.temp_path.name != f".tmp_{LEGACY_NAME}"
        assert a.sha256 == b.sha256 == hashlib.sha256(PDF_V1).hexdigest()
    finally:
        a.cleanup()
        b.cleanup()
    assert list((tmp_path / "in").glob(".tmp_*")) == []


def test_validation_failure_cleans_temp_file(doc_settings, gem, tmp_path):
    gem.script = [httpx.Response(200, content=b"<html>not a pdf</html>", headers={"content-type": "application/pdf"})]
    dl = DocumentDownloader(doc_settings, transport=httpx.MockTransport(gem), sleep=lambda s: None)
    with pytest.raises(InvalidFileError):
        dl.fetch(SOURCE_URL, tmp_path / "in")
    assert list((tmp_path / "in").glob(".tmp_*")) == []


def test_html_masquerading_as_pdf_is_rejected_via_service(service, db, tender, gem, doc_settings):
    gem.script = [httpx.Response(200, content=b"<html>Service page</html>", headers={"content-type": "application/pdf"})]
    r = run(service, db, tender)
    assert r["failed"] == 1 and r["downloaded"] == 0 and r["status"] == "FAILED"
    assert r["outcome"] == "PERMANENT_FAILURE"
    assert counts(db) == (0, 0)
    assert temp_files(doc_settings) == [] and stored_files(doc_settings) == []


def test_file_too_large_cleans_up(doc_settings, gem, tmp_path):
    small = doc_settings.model_copy(update={"max_document_size_mb": 1})
    gem.body = b"%PDF-" + b"0" * (2 * 1024 * 1024)
    dl = DocumentDownloader(small, transport=httpx.MockTransport(gem), sleep=lambda s: None)
    with pytest.raises(FileTooLargeError):
        dl.fetch(SOURCE_URL, tmp_path / "in")
    assert list((tmp_path / "in").glob(".tmp_*")) == []


def test_storage_failure_cleans_temp_and_reports_failure(service, db, tender, doc_settings, monkeypatch):
    def boom(src, dst):
        raise OSError("disk exploded")

    monkeypatch.setattr(DocumentsService, "_publish_no_overwrite", staticmethod(boom))
    r = run(service, db, tender)
    assert r["failed"] == 1 and r["downloaded"] == 0 and r["status"] == "FAILED"
    assert counts(db)[1] == 0
    assert temp_files(doc_settings) == []


# ---------------------------------------------------------------------------
# 8-13. network failure accounting and retry policy
# ---------------------------------------------------------------------------
def test_persistent_connection_reset_is_a_truthful_failure(service, db, tender, gem, sleeps):
    reset = httpx.ReadError("[WinError 10054] An existing connection was forcibly closed by the remote host")
    gem.script = [reset, reset, reset]

    r = run(service, db, tender)

    assert gem.calls == 3  # conservative: exactly 3 attempts
    assert r["failed"] == 1 and r["discovered"] == 0 and r["downloaded"] == 0
    assert r["status"] == "FAILED" and r["outcome"] == "TRANSIENT_FAILURE" and r["retryable"] is True
    assert "3 transient attempt" in r["error"] and "10054" in r["error"]
    assert sleeps == [1.0, 2.0]  # exponential backoff between attempts


def test_transient_failure_leaves_existing_v1_intact(service, db, tender, gem, doc_settings):
    run(service, db, tender)
    gem.script = [httpx.ConnectError("reset")] * 3

    r = run(service, db, tender)

    assert r["outcome"] == "TRANSIENT_FAILURE" and r["failed"] == 1
    assert counts(db) == (1, 1)
    assert len(stored_files(doc_settings)) == 1
    assert temp_files(doc_settings) == []


def test_connection_reset_then_success_retries_once(service, db, tender, gem, sleeps):
    gem.script = [httpx.ReadError("[WinError 10054] connection reset")]
    r = run(service, db, tender)
    assert gem.calls == 2 and sleeps == [1.0]
    assert (r["downloaded"], r["failed"]) == (1, 0)


def test_timeout_is_retried(service, db, tender, gem, sleeps):
    gem.script = [httpx.ReadTimeout("slow")]
    r = run(service, db, tender)
    assert gem.calls == 2 and (r["downloaded"], r["failed"]) == (1, 0)


def test_http_500_is_retried_up_to_three_attempts(service, db, tender, gem, sleeps):
    gem.script = [httpx.Response(500), httpx.Response(503)]
    r = run(service, db, tender)
    assert gem.calls == 3 and sleeps == [1.0, 2.0]
    assert (r["downloaded"], r["failed"]) == (1, 0)


def test_http_500_forever_fails_after_three_attempts(service, db, tender, gem):
    gem.script = [httpx.Response(500), httpx.Response(502), httpx.Response(504)]
    r = run(service, db, tender)
    assert gem.calls == 3
    assert r["outcome"] == "TRANSIENT_FAILURE" and r["failed"] == 1 and counts(db) == (0, 0)


def test_http_429_retry_after_is_respected(service, db, tender, gem, sleeps):
    gem.script = [httpx.Response(429, headers={"Retry-After": "7"})]
    r = run(service, db, tender)
    assert sleeps == [7.0]
    assert (r["downloaded"], r["failed"]) == (1, 0)


def test_http_429_retry_after_is_capped(service, db, tender, gem, sleeps):
    gem.script = [httpx.Response(429, headers={"Retry-After": "99999"})]
    run(service, db, tender)
    assert sleeps == [300.0]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_denied_is_blocked_and_not_retried(service, db, tender, gem, sleeps, status):
    gem.script = [httpx.Response(status)]
    r = run(service, db, tender)
    assert gem.calls == 1 and sleeps == []
    assert r["status"] == "BLOCKED" and r["outcome"] == "BLOCKED_BY_HUMAN_VERIFICATION"
    assert r["failed"] == 1 and counts(db) == (0, 0)


def test_captcha_page_is_blocked_and_not_retried(service, db, tender, gem, sleeps, doc_settings):
    gem.script = [
        httpx.Response(200, content=b"<html>Please verify you are human</html>", headers={"content-type": "text/html"})
    ]
    r = run(service, db, tender)
    assert gem.calls == 1 and sleeps == []
    assert r["status"] == "BLOCKED" and r["outcome"] == "BLOCKED_BY_HUMAN_VERIFICATION"
    assert counts(db) == (0, 0) and stored_files(doc_settings) == [] and temp_files(doc_settings) == []


def test_http_404_is_permanent_not_retried(service, db, tender, gem, sleeps):
    gem.script = [httpx.Response(404)]
    r = run(service, db, tender)
    assert gem.calls == 1 and sleeps == []
    assert r["outcome"] == "PERMANENT_FAILURE" and r["failed"] == 1


def test_successful_page_without_documents_is_not_a_failure(service, db, tender):
    r = service.discover_and_download_tender_documents(db, tender.id, "<html><body>nothing</body></html>")
    assert r["status"] == "SUCCESS" and r["outcome"] == "SUCCESS_NO_DOCUMENTS"
    assert (r["discovered"], r["failed"]) == (0, 0)


# ---------------------------------------------------------------------------
# security preserved
# ---------------------------------------------------------------------------
def test_redirect_to_private_address_is_rejected(doc_settings, tmp_path):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret.pdf"})

    dl = DocumentDownloader(doc_settings, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(URLValidationError):
        dl.fetch(SOURCE_URL, tmp_path / "in")


def test_safe_redirect_is_followed(doc_settings, tmp_path):
    def handler(request):
        if request.url.path.endswith("/start"):
            return httpx.Response(302, headers={"location": "https://bidplus.gem.gov.in/final.pdf"})
        return pdf_response()

    dl = DocumentDownloader(doc_settings, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    res = dl.fetch("https://bidplus.gem.gov.in/start", tmp_path / "in")
    try:
        assert res.file is not None and res.final_url.endswith("/final.pdf")
    finally:
        res.file.cleanup()


def test_unsafe_urls_rejected_before_any_request(doc_settings, gem, tmp_path):
    dl = DocumentDownloader(doc_settings, transport=httpx.MockTransport(gem), sleep=lambda s: None)
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/plain,hi", "http://localhost/x.pdf"):
        with pytest.raises(URLValidationError):
            dl.fetch(bad, tmp_path / "in")
    assert gem.calls == 0


def test_filenames_are_sanitized_and_version_names_bounded():
    assert DocumentDownloader._sanitize_filename("../../evil.pdf") == "evil.pdf"
    assert DocumentDownloader._sanitize_filename("a\\b\\c:d?.pdf") == "c_d_.pdf"
    name = DocumentsService.version_filename(12, "ab" * 32, "x" * 400 + ".pdf")
    assert name.startswith("v12_abababababab_") and name.endswith(".pdf") and len(name) <= 180


def test_publish_never_overwrites_existing_file(tmp_path):
    src = tmp_path / "src.part"
    dst = tmp_path / "dst.pdf"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        DocumentsService._publish_no_overwrite(src, dst)
    assert dst.read_bytes() == b"old"


def test_name_collision_with_different_content_gets_counter_suffix(service, doc_settings, tmp_path):
    target_dir = main_bid_dir(doc_settings)
    target_dir.mkdir(parents=True)
    name = DocumentsService.version_filename(1, hashlib.sha256(PDF_V1).hexdigest(), LEGACY_NAME)
    (target_dir / name).write_bytes(b"%PDF-unrelated orphan")
    tmp = tmp_path / "x.part"
    tmp.write_bytes(PDF_V1)
    dl = DownloadedFile(
        temp_path=tmp, sha256=hashlib.sha256(PDF_V1).hexdigest(), file_size=len(PDF_V1), url=SOURCE_URL,
        final_url=SOURCE_URL, http_status=200, content_type="application/pdf", content_disposition=None,
        extension="pdf",
    )
    final, created = service._store_version_file(dl, target_dir, 1, LEGACY_NAME)
    assert created and final.name.endswith("-1.pdf") and final.read_bytes() == PDF_V1
    assert (target_dir / name).read_bytes() == b"%PDF-unrelated orphan"


# ---------------------------------------------------------------------------
# 15 / 16. manifest
# ---------------------------------------------------------------------------
def test_manifest_after_unchanged_acquisition_points_to_v1(service, db, tender, doc_settings):
    run(service, db, tender)
    run(service, db, tender)
    m = generate_manifest(db, tender)
    doc = m["documents"][0]
    assert doc["type"] == "MAIN_BID" and doc["current_version_number"] == 1
    assert [v["number"] for v in doc["versions"]] == [1]
    assert doc["versions"][0]["current"] is True
    path = write_manifest(doc_settings, tender, m)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["documents"][0]["current_version_number"] == 1
    assert (storage(doc_settings) / on_disk["documents"][0]["versions"][0]["storage"]).exists()


def test_manifest_after_v2_points_to_v2_and_keeps_v1_history(service, db, tender, gem, doc_settings):
    run(service, db, tender)
    gem.body = PDF_V2
    run(service, db, tender)
    doc = generate_manifest(db, tender)["documents"][0]
    assert doc["current_version_number"] == 2
    assert [v["number"] for v in doc["versions"]] == [1, 2]
    assert [v["current"] for v in doc["versions"]] == [False, True]
    for v in doc["versions"]:
        assert (storage(doc_settings) / v["storage"]).exists()
