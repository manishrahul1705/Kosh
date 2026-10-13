"""Bounded live GeM/Gemini validation against a verified backup copy, never production."""
import argparse, json, logging, sqlite3, sys, time, shutil
from pathlib import Path
from datetime import timedelta
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import select, func, text
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.database.session import build_engine, build_session_factory
from app.database.models import (Tender, TenderDocument, DocumentVersion, AIAnalysisRun,
    AIRequirement, AIProviderCall, EligibilityRequirementResult)
from app.database.matching_models import SellerTenderMatch
from app.documents.documents_service import DocumentsService
from app.documents.references import ReferenceDiscovery
from app.extraction.service import ExtractionService
from app.fields.service import FieldExtractionService
from app.corpus.service import build_corpus
from app.corpus.queue import enqueue_corpus
from app.ai.job_worker import AIAnalysisJobWorker
from app.eligibility.service import EligibilityService
from app.matching.service import MatchingService
from app.services.status_service import verify_statuses
from app.main import create_app
from app.api.auth import get_current_user
from app.core.supabase_auth import AuthenticatedIdentity
from app.utils.dates import utcnow
from tests.matching_factories import make_seller


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tender-ids", default="2648,6278,6270")
    parser.add_argument("--output", default="validation/real-e2e")
    parser.add_argument("--documents-only", action="store_true", help="Never invoke an external AI provider")
    args = parser.parse_args()
    ids = [int(i) for i in args.tender_ids.split(",")]
    if not 1 <= len(ids) <= 4:
        raise ValueError("Bounded sample: one to four tenders")
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / "validation"):
        raise ValueError("Staging output must be within validation")
    out.mkdir(parents=True, exist_ok=True)
    target = out / "staging.db"
    if target.exists():
        raise ValueError("Existing staging data is preserved; use a new output")
    backup = json.loads((ROOT / "validation/database-backup.json").read_text())
    source = sqlite3.connect(Path(backup["backup"]).as_uri() + "?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    source.backup(destination)
    destination.close(); source.close()
    live = Settings()
    cfg = live.model_copy(update={"database_url": "sqlite:///" + target.as_posix(),
        "document_storage_path": str(out / "documents"), "auto_migrate": False,
        "scheduler_enabled": False, "collect_on_startup": False, "startup_recovery_enabled": False,
        "dev_login_enabled": False, "app_startup_mode": "normal", "log_level": "WARNING",
        "lock_file": str(out / "collection.lock"), "debug_dir": str(out / "debug"),
        "document_worker_enabled": False, "extraction_worker_enabled": False,
        "field_extraction_worker_enabled": False, "ai_analysis_worker_enabled": False,
        "extraction_auto_queue": False, "field_extraction_auto_queue": False,
        "ai_analysis_auto_queue": False, "document_max_retries": 1,
        "document_request_timeout_seconds": 25, "document_request_delay_seconds": 1,
        "ai_max_retries": 0, "ai_request_timeout_seconds": 90, "ai_max_analyses_per_day": 20,
        "ai_analysis_scope": "TENDER_CORPUS"})
    engine = build_engine(cfg.resolved_database_url)
    factory = build_session_factory(engine)
    report = {"database": str(target), "production_mutated": False,
        "provider": cfg.ai_provider, "model": cfg.ai_model, "sample": [], "timings_ms": {}}
    def timed(name, fn):
        at = time.perf_counter()
        result = fn()
        report["timings_ms"].setdefault(name, []).append((time.perf_counter() - at) * 1000)
        return result
    def save():
        (out / "results.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    with factory() as db:
        report["tender_count_before"] = db.scalar(select(func.count()).select_from(Tender))
        sellers = [make_seller(db, name="Validation strong computer seller", terms="Computer,Workstation,Laptop",
                    turnover=1_000_000_000, years=30, oem=True,
                    owner_subject="eeeeeeee-0000-0000-0000-000000000001"),
                   make_seller(db, name="Validation incomplete computer seller", terms="Computer,Workstation,Laptop",
                    turnover=None, years=None, iso=False,
                    owner_subject="eeeeeeee-0000-0000-0000-000000000002")]
        seller_ids = [s.id for s in sellers]
        verify_statuses(db, now=utcnow()); db.commit()
    document_service = DocumentsService(cfg)
    for tid in ids:
        row = {"tender_id": tid, "stages": {}}
        report["sample"].append(row)
        with factory() as db:
            tender = db.get(Tender, tid)
            if tender is None:
                row["error"] = "Tender absent from backup"; save(); continue
            row.update(bid_number=tender.bid_number, category=tender.category, current_status=tender.current_status)
            # Real cached source is used only as a fallback; it is explicitly marked below.
            versions_before = list(db.scalars(select(DocumentVersion).join(TenderDocument,
                DocumentVersion.document_id == TenderDocument.id).where(TenderDocument.tender_id == tid)))
            outcome = timed("live_document_package", lambda: document_service.discover_and_download_tender_documents(db, tid))
            row["stages"]["live_documents"] = outcome
            if outcome.get("outcome") == "BLOCKED":
                row["access_block"] = True
            cached = []
            for version in versions_before:
                if version.storage_path:
                    src = live.resolved_document_storage_path / version.storage_path
                    dst = cfg.resolved_document_storage_path / version.storage_path
                    if src.is_file() and not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        cached.append(version.id)
            row["cached_source_versions_copied"] = cached
            row["stages"]["references"] = ReferenceDiscovery(document_service).run(db, tender,
                acquire=not row.get("access_block", False), retry_failed=False)
            version_ids = list(db.scalars(select(TenderDocument.current_version_id).where(
                TenderDocument.tender_id == tid, TenderDocument.is_active.is_(True),
                TenderDocument.current_version_id.is_not(None))))
        extraction_ids = []
        for vid in version_ids:
            a = timed("stage3a", lambda vid=vid: ExtractionService(cfg, factory).extract_version(vid))
            row["stages"].setdefault("stage3a", []).append(vars(a))
            if a.extraction_id:
                b = timed("stage3b", lambda: FieldExtractionService(cfg, factory).extract(a.extraction_id, force=True))
                row["stages"].setdefault("stage3b", []).append(vars(b))
                extraction_ids.append(a.extraction_id)
        with factory() as db:
            corpus = timed("corpus", lambda: build_corpus(db, tid))
            row["stages"]["corpus"] = {k: corpus[k] for k in (
                "fingerprint", "complete", "completeness", "relevant_document_count", "missing_reference_count", "documents", "reasons")}
            queued = enqueue_corpus(db, tid, cfg, force=True, reason="MANUAL")
            db.commit()
        if queued.job_id and not args.documents_only:
            result = timed("live_ai_worker", lambda: AIAnalysisJobWorker(cfg, factory).run_batch(
                max_jobs=1, job_id=queued.job_id))
            row["stages"]["ai"] = [vars(j) for j in result.jobs]
        elif args.documents_only:
            row["stages"]["ai"] = "NOT_RUN: external AI approval pending"
        with factory() as db:
            row["stages"]["eligibility"] = []
            for sid in seller_ids:
                evaluation = EligibilityService(db).evaluate_tender(tid, sid)
                row["stages"]["eligibility"].append({"seller_id": sid, "run_id": evaluation.id,
                    "status": evaluation.status, "passed": evaluation.passed_count,
                    "failed": evaluation.failed_count, "review": evaluation.review_count,
                    "insufficient": evaluation.insufficient_count})
            row["stages"]["matching"] = timed("matching", lambda: MatchingService(db).recalculate(
                now=utcnow(), seller_ids=seller_ids, tender_ids=[tid])).as_dict()
            row["matches"] = [{"seller_id": m.seller_id, "status": m.match_status,
                "passed": m.passed_count, "failed": m.failed_count, "review": m.review_count}
                for m in db.scalars(select(SellerTenderMatch).where(SellerTenderMatch.tender_id == tid,
                                                                  SellerTenderMatch.seller_id.in_(seller_ids)))]
        save()
    app = create_app(cfg, session_factory=factory)
    with TestClient(app) as client:
        for row in report["sample"]:
            row["portal"] = []
            for index, sid in enumerate(seller_ids):
                subject = f"eeeeeeee-0000-0000-0000-{index+1:012d}"
                app.dependency_overrides[get_current_user] = lambda subject=subject: AuthenticatedIdentity(
                    subject=subject, email=None, claims={"sub": subject, "role": "authenticated"})
                response = timed("portal_detail", lambda: client.get(
                    f"/api/portal/sellers/{sid}/tenders/{row['tender_id']}"))
                row["portal"].append({"seller_id": sid, "status_code": response.status_code,
                    "analysis_status": response.json().get("analysis_status"),
                    "document_count": len(response.json().get("documents", []))})
    with factory() as db:
        report["tender_count_after"] = db.scalar(select(func.count()).select_from(Tender))
        report["foreign_keys"] = [list(r) for r in db.execute(text("PRAGMA foreign_key_check"))]
        report["integrity"] = db.execute(text("PRAGMA integrity_check")).scalars().all()
        report["provider_calls"] = [{"provider": r.provider, "model": r.model, "status": r.status,
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "duration_ms": r.duration_ms}
            for r in db.scalars(select(AIProviderCall).where(AIProviderCall.started_at >= utcnow() - timedelta(hours=1)))]
    save()
    print(json.dumps(report, default=str))
    engine.dispose()


if __name__ == "__main__":
    main()
