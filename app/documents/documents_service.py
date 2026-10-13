"""Stage 2 documents service: orchestrates discovery, download, dedup and storage.

Idempotent acquisition flow (per document candidate)
----------------------------------------------------
    stream to UNIQUE temp file -> validate -> SHA-256
        -> find logical TenderDocument
        -> same SHA-256 as an existing DocumentVersion?
             YES -> UNCHANGED: delete temp, no new version, no file written
             NO  -> next version number -> version-aware final name ->
                    atomic no-overwrite publish -> DocumentVersion -> current_version_id

The final path of an existing version is never opened for writing, so a legacy
file such as ``GeM-Bidding-9988704.pdf`` can never collide (WinError 183).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.models import (
    DocumentEvent,
    DocumentVersion,
    Tender,
    TenderDocument,
)
from app.documents.classifier import classify_document
from app.documents.discovery import (
    BlockedByVerification,
    DiscoveryPermanentError,
    DiscoveryResult,
    DiscoveryTransientError,
    DocumentDiscovery,
)
from app.documents.downloader import (
    TEMP_PREFIX,
    BlockedDownloadError,
    DocumentDownloader,
    DownloadedFile,
    DownloadError,
    FileTooLargeError,
    InvalidFileError,
    TransientDownloadError,
    URLValidationError,
)
from app.extraction.job_queue import queue_after_version_commit
from app.schemas.documents import DocumentEventType
from app.utils.dates import utcnow

logger = logging.getLogger("app.documents.documents_service")

# Outcome vocabulary (summary["outcome"]) - truthful, never "0 documents" for a failure.
OUTCOME_WITH_DOCUMENTS = "SUCCESS_WITH_DOCUMENTS"
OUTCOME_NO_DOCUMENTS = "SUCCESS_NO_DOCUMENTS"
OUTCOME_TRANSIENT = "TRANSIENT_FAILURE"
OUTCOME_BLOCKED = "BLOCKED_BY_HUMAN_VERIFICATION"
OUTCOME_PERMANENT = "PERMANENT_FAILURE"

STALE_TEMP_MAX_AGE_SECONDS = 24 * 3600
MAX_FINAL_NAME_COLLISIONS = 20


@dataclass
class CandidateOutcome:
    """Result of processing one candidate."""

    kind: str  # DOWNLOADED | UPDATED | UNCHANGED | FAILED
    version_number: int | None = None
    message: str | None = None
    failure_class: str | None = None  # TRANSIENT | BLOCKED | PERMANENT (FAILED only)


class DocumentsService:
    """Orchestrates document discovery, download, and storage for tenders."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        sleep=None,
    ):
        self.settings = settings
        self.downloader = DocumentDownloader(settings, transport=transport, sleep=sleep)
        self.discovery = DocumentDiscovery(settings, downloader=self.downloader)
        self.storage_root = settings.resolved_document_storage_path
        self.incoming_dir = self.storage_root / "_incoming"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def discover_and_download_tender_documents(
        self,
        db: Session,
        tender_id: int,
        page_html: str | None = None,
    ) -> dict:
        """Discover and download all documents for a tender.

        Returns summary: {
            'tender_id', 'status': 'SUCCESS'|'PARTIAL_SUCCESS'|'FAILED'|'BLOCKED',
            'outcome': SUCCESS_WITH_DOCUMENTS | SUCCESS_NO_DOCUMENTS | TRANSIENT_FAILURE |
                       BLOCKED_BY_HUMAN_VERIFICATION | PERMANENT_FAILURE,
            'retryable': bool,
            'discovered', 'downloaded', 'unchanged', 'failed': int,
            'errors': [str], 'error': str | None,
        }
        """
        tender = db.scalar(select(Tender).where(Tender.id == tender_id))
        if not tender:
            return {
                "tender_id": tender_id,
                "status": "FAILED",
                "outcome": OUTCOME_PERMANENT,
                "retryable": False,
                "discovered": 0,
                "downloaded": 0,
                "unchanged": 0,
                "failed": 1,
                "error": "Tender not found",
                "errors": ["Tender not found"],
            }

        summary: dict = {
            "tender_id": tender_id,
            "status": "RUNNING",
            "outcome": None,
            "retryable": False,
            "discovered": 0,
            "downloaded": 0,
            "unchanged": 0,
            "failed": 0,
            "errors": [],
            "error": None,
        }

        self._sweep_stale_temp_files()

        result: DiscoveryResult | None = None
        try:
            db.commit()  # Release the tender lookup snapshot before GeM HTTP discovery.
            try:
                result = self.discovery.discover(tender, page_html, temp_dir=self.incoming_dir)
            except BlockedByVerification as e:
                return self._finish_discovery_failure(
                    db, tender, summary, "BLOCKED", OUTCOME_BLOCKED, str(e), retryable=False
                )
            except DiscoveryTransientError as e:
                return self._finish_discovery_failure(
                    db, tender, summary, "FAILED", OUTCOME_TRANSIENT, str(e), retryable=True
                )
            except DiscoveryPermanentError as e:
                return self._finish_discovery_failure(
                    db, tender, summary, "FAILED", OUTCOME_PERMANENT, str(e), retryable=False
                )

            candidates = result.candidates
            summary["discovered"] = len(candidates)

            if not candidates:
                logger.info(f"No documents found on tender {tender_id} (page fetched successfully)")
                summary["status"] = "SUCCESS"
                summary["outcome"] = OUTCOME_NO_DOCUMENTS
                return summary

            failure_classes: list[str] = []
            for candidate in candidates:
                try:
                    outcome = self._process_document_candidate(db, tender, candidate, result)
                except Exception as e:  # unexpected (I/O, DB ...): never counted as success
                    db.rollback()
                    logger.exception(f"Unexpected error processing {candidate.document_key}")
                    outcome = CandidateOutcome(
                        "FAILED",
                        message=f"Failed to process {candidate.document_key}: {type(e).__name__}: {e}",
                        failure_class="PERMANENT",
                    )

                if outcome.kind in ("DOWNLOADED", "UPDATED"):
                    summary["downloaded"] += 1
                elif outcome.kind == "UNCHANGED":
                    summary["unchanged"] += 1
                else:
                    summary["failed"] += 1
                    failure_classes.append(outcome.failure_class or "PERMANENT")
                    if outcome.message:
                        summary["errors"].append(outcome.message)

            if self.settings.document_reference_discovery_enabled:
                from app.documents.references import ReferenceDiscovery
                try:
                    summary["references"] = ReferenceDiscovery(self).run(db, tender)
                except Exception:
                    db.rollback()
                    logger.exception("reference_discovery_failed tender_id=%s", tender.id)
                    summary["failed"] += 1
                    summary["errors"].append("Reference discovery failed; corpus remains incomplete")
            summary["error"] = summary["errors"][0] if summary["errors"] else None
            ok = summary["downloaded"] + summary["unchanged"]

            if summary["failed"] == 0:
                summary["status"] = "SUCCESS"
                summary["outcome"] = OUTCOME_WITH_DOCUMENTS
            elif ok > 0:
                summary["status"] = "PARTIAL_SUCCESS"
                summary["outcome"] = OUTCOME_WITH_DOCUMENTS
                summary["retryable"] = "TRANSIENT" in failure_classes
            else:
                if all(c == "BLOCKED" for c in failure_classes):
                    summary["status"] = "BLOCKED"
                    summary["outcome"] = OUTCOME_BLOCKED
                elif "TRANSIENT" in failure_classes and all(
                    c in ("TRANSIENT", "BLOCKED") for c in failure_classes
                ):
                    summary["status"] = "FAILED"
                    summary["outcome"] = OUTCOME_TRANSIENT
                    summary["retryable"] = True
                else:
                    summary["status"] = "FAILED"
                    summary["outcome"] = OUTCOME_PERMANENT
            return summary

        except Exception as e:
            db.rollback()
            logger.exception(f"Error processing documents for tender {tender_id}")
            summary["status"] = "FAILED"
            summary["outcome"] = OUTCOME_PERMANENT
            summary["failed"] = max(1, summary["failed"])
            summary["error"] = f"{type(e).__name__}: {e}"
            summary["errors"].append(summary["error"])
            return summary
        finally:
            if result is not None:
                result.cleanup()  # remove any prefetched temp file nobody consumed

    def _finish_discovery_failure(
        self,
        db: Session,
        tender: Tender,
        summary: dict,
        status: str,
        outcome: str,
        message: str,
        retryable: bool,
    ) -> dict:
        logger.warning(f"Tender {tender.id} discovery failed [{outcome}]: {message}")
        summary["status"] = status
        summary["outcome"] = outcome
        summary["retryable"] = retryable
        summary["failed"] = 1  # a failed discovery is a failure, never "0 documents, 0 failed"
        summary["error"] = message
        summary["errors"].append(message)
        return summary

    # ------------------------------------------------------------------
    # One candidate
    # ------------------------------------------------------------------
    def _process_document_candidate(
        self,
        db: Session,
        tender: Tender,
        candidate,
        discovery_result: DiscoveryResult | None = None,
    ) -> CandidateOutcome:
        """Acquire one candidate idempotently. Commits on success."""
        from app.database.session import reserve_sqlite_writer
        reserve_sqlite_writer(db)
        classified_type = classify_document(candidate.display_name, candidate.original_filename)

        storage_tender_dir = self._get_tender_storage_dir(tender)
        doc_type_dir = storage_tender_dir / classified_type.value.lower()

        doc_key = candidate.document_key or f"{classified_type.value.lower()}_1"
        tender_doc = db.scalar(
            select(TenderDocument).where(
                (TenderDocument.tender_id == tender.id)
                & (TenderDocument.document_key == doc_key)
            )
        )

        if not tender_doc:
            tender_doc = TenderDocument(
                tender_id=tender.id,
                document_key=doc_key,
                document_type=classified_type.value,
                display_name=candidate.display_name,
                original_filename=candidate.original_filename,
                source_url=candidate.source_url,
                discovered_at=utcnow(),
                last_seen_at=utcnow(),
                is_active=True,
            )
            db.add(tender_doc)
            db.flush()
            db.add(
                DocumentEvent(
                    document_id=tender_doc.id,
                    event_type=DocumentEventType.DISCOVERED.value,
                    detected_at=utcnow(),
                    details=f"Discovered from {candidate.source_url}",
                )
            )
            logger.info(f"Discovered document: {tender_doc.id} ({doc_key})")
        else:
            tender_doc.last_seen_at = utcnow()
            tender_doc.is_active = True

        # ---- acquire (reuse the discovery fetch for direct PDFs) ---------
        downloaded: DownloadedFile | None = None
        try:
            if discovery_result is not None:
                downloaded = discovery_result.take_prefetched(candidate.source_url)
            if downloaded is None:
                # Stage 2B: never hold a SQLite write transaction across a GeM
                # request. The flushed DISCOVERED/last_seen bookkeeping is committed
                # first (the failure path below commits it anyway via _fail), so
                # Stage 1 / the API can write while this download is in flight.
                # Direct-PDF candidates (prefetched) never reach this branch.
                db.commit()
                fetched = self.downloader.fetch(
                    candidate.source_url,
                    self.incoming_dir,
                    candidate.original_filename,
                    allow_page=False,
                )
                downloaded = fetched.file
            if downloaded is None:  # pragma: no cover - allow_page=False never returns a page
                raise InvalidFileError("INVALID_FILE", "No file content returned")
        except FileTooLargeError as e:
            return self._fail(db, tender_doc, DocumentEventType.DOWNLOAD_FAILED, "FILE_TOO_LARGE", e.message, "PERMANENT")
        except InvalidFileError as e:
            return self._fail(db, tender_doc, DocumentEventType.INVALID_FILE, "INVALID_FILE", e.message, "PERMANENT")
        except URLValidationError as e:
            return self._fail(db, tender_doc, DocumentEventType.DOWNLOAD_FAILED, "UNSAFE_URL", e.message, "PERMANENT")
        except BlockedDownloadError as e:
            return self._fail(db, tender_doc, DocumentEventType.BLOCKED, e.code, e.message, "BLOCKED")
        except TransientDownloadError as e:
            return self._fail(db, tender_doc, DocumentEventType.DOWNLOAD_FAILED, e.code, e.message, "TRANSIENT")
        except DownloadError as e:
            return self._fail(db, tender_doc, DocumentEventType.DOWNLOAD_FAILED, e.code, e.message, "PERMANENT")

        # ---- dedup by SHA-256, then store -------------------------------
        published: Path | None = None  # file WE created and must remove if DB work fails
        try:
            existing_version = db.scalar(
                select(DocumentVersion).where(
                    (DocumentVersion.document_id == tender_doc.id)
                    & (DocumentVersion.sha256 == downloaded.sha256)
                )
            )

            if existing_version is not None:
                return self._record_unchanged(db, tender_doc, existing_version, downloaded)

            # New content -> new version.
            max_version = db.scalar(
                select(func.max(DocumentVersion.version_number)).where(
                    DocumentVersion.document_id == tender_doc.id
                )
            )
            next_version_number = (max_version or 0) + 1
            previous_version = None
            if max_version:
                previous_version = db.scalar(
                    select(DocumentVersion).where(
                        (DocumentVersion.document_id == tender_doc.id)
                        & (DocumentVersion.version_number == max_version)
                    )
                )

            safe_name = self.downloader.suggest_filename(downloaded, candidate.original_filename)
            final_path, created = self._store_version_file(
                downloaded, doc_type_dir, next_version_number, safe_name
            )
            if created:
                published = final_path

            extension = (downloaded.extension or final_path.suffix.lstrip(".")).lower()
            new_version = DocumentVersion(
                document_id=tender_doc.id,
                version_number=next_version_number,
                sha256=downloaded.sha256,
                file_size=downloaded.file_size,
                mime_type=self._guess_mime_type(extension),
                extension=extension,
                storage_path=final_path.relative_to(self.storage_root).as_posix(),
                source_url=candidate.source_url,
                final_url=downloaded.final_url or candidate.source_url,
                downloaded_at=downloaded.downloaded_at,
                http_status=downloaded.http_status or 200,
                validation_status="VALID",
            )
            db.add(new_version)
            db.flush()

            tender_doc.current_version_id = new_version.id

            if previous_version is not None:
                event_type = DocumentEventType.UPDATED.value
                old_version_id = previous_version.id
            else:
                event_type = DocumentEventType.DOWNLOADED.value
                old_version_id = None

            db.add(
                DocumentEvent(
                    document_id=tender_doc.id,
                    event_type=event_type,
                    old_version_id=old_version_id,
                    new_version_id=new_version.id,
                    detected_at=utcnow(),
                    details=f"Downloaded {downloaded.file_size} bytes (hash: {downloaded.sha256})",
                )
            )
            db.commit()
            published = None  # committed: the file now belongs to the version record
            # Stage 3A: queue text extraction only AFTER the version is durable.
            # Never raises and never changes this Stage 2 outcome.
            self._queue_extraction(db, new_version.id)

            logger.info(
                f"Downloaded document {tender_doc.id} version {next_version_number} "
                f"({downloaded.file_size} bytes, {downloaded.sha256[:16]}...)"
            )
            return CandidateOutcome(
                "UPDATED" if previous_version is not None else "DOWNLOADED",
                version_number=next_version_number,
            )
        except BaseException:
            db.rollback()
            if published is not None:
                try:
                    published.unlink(missing_ok=True)
                except OSError:  # pragma: no cover
                    logger.warning(f"Could not remove uncommitted file {published}")
            raise
        finally:
            downloaded.cleanup()  # always remove the temp file (new version, unchanged, failure)

    def _queue_extraction(self, db: Session, version_id: int) -> None:
        """Stage 3A hook (see app/extraction/job_queue.queue_after_version_commit)."""
        try:
            queue_after_version_commit(db, version_id, self.settings)
        except Exception:  # pragma: no cover - the hook already swallows; belt and braces
            logger.exception(f"extraction_job_queue_failed document_version_id={version_id}")

    # ------------------------------------------------------------------
    # UNCHANGED
    # ------------------------------------------------------------------
    def _record_unchanged(
        self,
        db: Session,
        tender_doc: TenderDocument,
        existing_version: DocumentVersion,
        downloaded: DownloadedFile,
    ) -> CandidateOutcome:
        """Same bytes as a stored version: record UNCHANGED, create nothing."""
        note = f"Content identical to v{existing_version.version_number}"
        if tender_doc.current_version_id is None:
            tender_doc.current_version_id = existing_version.id  # repair a missing pointer only
        elif tender_doc.current_version_id != existing_version.id:
            note += " (not the current version; current version left unchanged)"

        # Self-heal: the recorded file vanished from disk -> restore it WITHOUT overwriting anything.
        restored = self._restore_missing_file(existing_version, downloaded)
        if restored:
            note += "; missing stored file restored"

        db.add(
            DocumentEvent(
                document_id=tender_doc.id,
                event_type=DocumentEventType.UNCHANGED.value,
                new_version_id=existing_version.id,
                detected_at=utcnow(),
                details=note,
            )
        )
        db.commit()
        logger.info(f"Document {tender_doc.id} version {existing_version.version_number} unchanged")
        return CandidateOutcome("UNCHANGED", version_number=existing_version.version_number)

    def _restore_missing_file(self, version: DocumentVersion, downloaded: DownloadedFile) -> bool:
        if not version.storage_path:
            return False
        target = self._resolve_storage_path(version.storage_path)
        if target is None or target.exists():
            return False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._publish_no_overwrite(downloaded.temp_path, target)
            logger.warning(f"Restored missing stored file {target}")
            return True
        except FileExistsError:
            return False
        except OSError as e:
            logger.warning(f"Could not restore missing file {target}: {e}")
            return False

    # ------------------------------------------------------------------
    # Failure recording
    # ------------------------------------------------------------------
    def _fail(
        self,
        db: Session,
        tender_doc: TenderDocument,
        event_type: DocumentEventType,
        code: str,
        message: str,
        failure_class: str,
    ) -> CandidateOutcome:
        logger.warning(f"Document {tender_doc.id} acquisition failed: {code}: {message}")
        db.add(
            DocumentEvent(
                document_id=tender_doc.id,
                event_type=event_type.value,
                detected_at=utcnow(),
                details=f"{code}: {message}",
            )
        )
        db.commit()  # keep DISCOVERED + failure event; existing versions are untouched
        return CandidateOutcome(
            "FAILED",
            message=f"{tender_doc.document_key}: {code}: {message}",
            failure_class=failure_class,
        )

    def _record_download_failure(
        self,
        db: Session,
        tender_doc: TenderDocument,
        error_code: str,
        error_message: str,
    ) -> None:
        """Record a download failure event (kept for compatibility)."""
        db.add(
            DocumentEvent(
                document_id=tender_doc.id,
                event_type=DocumentEventType.DOWNLOAD_FAILED.value,
                detected_at=utcnow(),
                details=f"{error_code}: {error_message}",
            )
        )

    # ------------------------------------------------------------------
    # File storage
    # ------------------------------------------------------------------
    def _store_version_file(
        self,
        downloaded: DownloadedFile,
        doc_type_dir: Path,
        version_number: int,
        safe_name: str,
    ) -> tuple[Path, bool]:
        """Publish the temp file under a version-aware, collision-safe name.

        Returns (final_path, created). ``created`` is False if an identical file
        was already there (e.g. orphan from an interrupted run) and was reused.
        Never overwrites an existing file.
        """
        doc_type_dir.mkdir(parents=True, exist_ok=True)
        final_name = self.version_filename(version_number, downloaded.sha256, safe_name)

        for n in range(MAX_FINAL_NAME_COLLISIONS + 1):
            candidate_name = final_name if n == 0 else self._with_suffix_counter(final_name, n)
            final_path = doc_type_dir / candidate_name
            self._assert_inside_storage(final_path)
            try:
                self._publish_no_overwrite(downloaded.temp_path, final_path)
                return final_path, True
            except FileExistsError:
                if self._sha256_of(final_path) == downloaded.sha256:
                    logger.info(f"Identical orphan file already at {final_path}; reusing")
                    return final_path, False
                continue
        raise OSError(f"Could not allocate a collision-free filename for {final_name}")

    @staticmethod
    def version_filename(version_number: int, sha256: str, safe_name: str, max_length: int = 180) -> str:
        """``v{n}_{sha12}_{name}`` - deterministic, Windows-safe, version-history-safe."""
        prefix = f"v{version_number}_{sha256[:12]}_"
        name = safe_name
        room = max_length - len(prefix)
        if len(name) > room:
            stem, dot, ext = name.rpartition(".")
            if dot and len(ext) < 10:
                name = stem[: max(1, room - len(ext) - 1)] + "." + ext
            else:
                name = name[:room]
        return prefix + name

    @staticmethod
    def _with_suffix_counter(name: str, n: int) -> str:
        stem, dot, ext = name.rpartition(".")
        return f"{stem}-{n}.{ext}" if dot else f"{name}-{n}"

    @staticmethod
    def _publish_no_overwrite(src: Path, dst: Path) -> None:
        """Atomically make ``dst`` appear with ``src``'s content; never replace an existing dst.

        Uses a hard link (atomic, fails with FileExistsError if dst exists) and
        falls back to an exclusive-create copy where hard links are unsupported.
        The temp file ``src`` is left for the caller to delete.
        """
        try:
            os.link(src, dst)
            return
        except FileExistsError:
            raise
        except OSError:
            pass  # hard links unsupported on this filesystem -> exclusive copy
        with open(src, "rb") as fin, open(dst, "xb") as fout:  # "x" => FileExistsError if present
            try:
                shutil.copyfileobj(fin, fout, 1024 * 1024)
                fout.flush()
                os.fsync(fout.fileno())
            except BaseException:
                fout.close()
                dst.unlink(missing_ok=True)  # remove only the partial file WE created
                raise

    @staticmethod
    def _sha256_of(path: Path) -> str | None:
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    def _resolve_storage_path(self, storage_path: str) -> Path | None:
        """Resolve a DB-stored relative path (legacy backslash or posix) inside the storage root."""
        candidate = (self.storage_root / Path(storage_path.replace("\\", "/"))).resolve()
        try:
            candidate.relative_to(self.storage_root.resolve())
        except ValueError:
            logger.error(f"Refusing storage path outside storage root: {storage_path}")
            return None
        return candidate

    def _assert_inside_storage(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.storage_root.resolve())
        except ValueError:
            raise OSError(f"Path escapes storage root: {path}")

    def _sweep_stale_temp_files(self) -> None:
        """Remove abandoned temp files (interrupted runs) older than 24h."""
        try:
            if not self.incoming_dir.exists():
                return
            cutoff = time.time() - STALE_TEMP_MAX_AGE_SECONDS
            for p in self.incoming_dir.glob(f"{TEMP_PREFIX}*"):
                try:
                    if p.is_file() and p.stat().st_mtime < cutoff:
                        p.unlink()
                except OSError:
                    pass
        except OSError:  # pragma: no cover
            pass

    def _get_tender_storage_dir(self, tender: Tender) -> Path:
        """Get storage directory for a tender's documents."""
        safe_bid = tender.bid_number.replace("/", "_")
        return self.storage_root / safe_bid / "documents"

    @staticmethod
    def _guess_mime_type(extension: str) -> str:
        """Guess MIME type from file extension."""
        mime_types = {
            "pdf": "application/pdf",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc": "application/msword",
            "zip": "application/zip",
            "csv": "text/csv",
            "txt": "text/plain",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "xml": "application/xml",
            "json": "application/json",
        }
        return mime_types.get(extension.lower(), "application/octet-stream")
