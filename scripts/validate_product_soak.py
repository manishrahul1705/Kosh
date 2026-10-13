"""Active, isolated staging validation. Uses real HTTP/SQLite/jobs; fixture GeM and mock AI.

Never opens the production DB. Private signing material and access tokens stay in memory.
Example: python scripts/validate_product_soak.py --seconds 7200 --output validation/soak
"""
from __future__ import annotations
import argparse, ctypes, json, logging, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx, jwt, uvicorn
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select, func
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from app.core.config import Settings
from app.core.constants import TriggerType
from app.core.supabase_auth import SupabaseTokenVerifier
from app.api.auth import get_token_verifier
from app.database.session import build_engine, build_session_factory, run_migrations, reserve_sqlite_writer
from app.database.models import (Tender, DocumentJob, ExtractionJob, FieldExtractionJob,
    AIAnalysisJob, DocumentVersion, TenderDocument, AIAnalysisRun, SellerAttribute, SellerRevision)
from app.database.matching_models import SellerTenderMatch
from app.documents.documents_service import DocumentsService
from app.documents.job_worker import DocumentJobWorker
from app.documents.job_queue import enqueue_job
from app.ai.service import AnalysisService
from app.ai.job_worker import AIAnalysisJobWorker
from app.ai.providers.mock import MockProvider
from app.collectors.gem_collector import GemListingCollector, PaginationLimits
from app.collectors.fixture_collector import FixtureTransport
from app.corpus.service import build_corpus
from app.services.status_service import verify_statuses
from app.matching.service import MatchingService
from app.main import create_app
from app.utils.dates import utcnow
from tests.pdf_factory import text_pdf
from tests.matching_factories import make_seller


def rss():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (n, ctypes.c_size_t) for n in ("peak", "working", "pagedpeak", "paged",
                "nonpagedpeak", "nonpaged", "pagefile", "pagefilepeak")]
    c = Counters()
    c.cb = ctypes.sizeof(c)
    get_handle = ctypes.windll.kernel32.GetCurrentProcess
    get_handle.restype = ctypes.c_void_p
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    handle = get_handle()
    if not get_memory(handle, ctypes.byref(c), c.cb):
        raise OSError("GetProcessMemoryInfo failed")
    return c.working


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=7200)
    parser.add_argument("--output", default="validation/soak")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # Temporary execution request: prevent automatic system sleep during the active
    # validation window. This is released at process exit; no power settings change.
    power = ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    if not power:
        raise OSError("Unable to establish temporary system-awake execution request")
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / "validation"):
        raise ValueError("Output must be inside project validation directory")
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "staging.db"
    if db_path.exists():
        raise ValueError("Use a new output directory; existing staging DB is preserved")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["SCHEDULER_ENABLED"] = "false"
    cfg = Settings(_env_file=None, database_url=os.environ["DATABASE_URL"], auto_migrate=False,
        startup_recovery_enabled=False, scheduler_enabled=True, collect_on_startup=False,
        collector_mode="fixture", collection_interval_minutes=1,
        document_storage_path=str(out / "documents"), lock_file=str(out / "collection.lock"),
        debug_dir=str(out / "debug"), document_worker_enabled=True, extraction_worker_enabled=True,
        field_extraction_worker_enabled=True, ai_analysis_worker_enabled=True,
        document_job_poll_seconds=5, extraction_job_poll_seconds=5,
        field_extraction_job_poll_seconds=5, ai_analysis_job_poll_seconds=5,
        document_inter_job_delay_seconds=0, document_request_delay_seconds=0,
        document_worker_max_jobs_per_run=10, extraction_worker_max_jobs_per_run=10,
        field_extraction_worker_max_jobs_per_run=10, ai_max_jobs_per_run=10,
        request_delay_seconds=0, ai_inter_job_delay_seconds=0,
        periodic_document_refresh_enabled=False, ai_provider="mock", ai_model="mock-soak",
        ai_api_key="", ai_max_analyses_per_day=10000, status_check_interval_minutes=1,
        matching_interval_minutes=1, app_env="production", dev_login_enabled=False,
        supabase_url="https://staging-validation.supabase.co", log_level="WARNING")
    run_migrations(cfg.resolved_database_url)
    engine = build_engine(cfg.resolved_database_url)
    factory = build_session_factory(engine)
    fixture = out / "listing"
    fixture.mkdir()
    template = json.loads((ROOT / "tests/fixtures/gem/default/page_1.json").read_text())
    docs = template["response"]["response"]["docs"][:3]
    for i, doc in enumerate(docs):
        doc["b_category_name"] = doc["bd_category_name"] = ["Desktop Computers"]
        doc["final_start_date_sort"] = [(utcnow() - timedelta(days=1)).isoformat() + "Z"]
        doc["final_end_date_sort"] = [(utcnow() + timedelta(days=3)).isoformat() + "Z"]
        if i == 1:
            doc["b_bid_number"] = ["GEM/2026/R/9000002"]
    template["response"]["response"]["docs"] = docs
    template["response"]["response"]["numFound"] = len(docs)
    (fixture / "page_1.json").write_text(json.dumps(template), encoding="utf-8")
    collector = lambda: GemListingCollector(FixtureTransport(fixture),
        source_origin="https://bidplus.gem.gov.in", limits=PaginationLimits(5, 0))
    generation = {"value": 0}
    quote = "The bidder must have annual turnover of INR 7 lakh."
    def download(request):
        content = text_pdf([["Bid Document - Desktop Computers", quote,
            "Generation " + str(generation["value"]), "Technical Specifications", "Desktop computer supply."]])
        return httpx.Response(200, content=content, headers={"content-type": "application/pdf"})
    document_worker = DocumentJobWorker(cfg, factory, service_factory=lambda: DocumentsService(
        cfg, transport=httpx.MockTransport(download), sleep=lambda _: None))
    def response(request):
        chunk = next(c for c in request.chunks if quote in c["text"])
        return {"summary": "Desktop computer tender", "requirements": [{
            "requirement_type": "TURNOVER", "title": "Annual turnover", "obligation_level": "MANDATORY",
            "applies_to": "BIDDER", "value": 7, "unit": "INR", "evidence": [
                {"chunk_id": chunk["chunk_id"], "quote": quote}]}]}
    provider = MockProvider(model="mock-soak", responses=[response] * 10000)
    ai = AnalysisService(cfg, factory, provider_factory=lambda: provider)
    ai_worker = AIAnalysisJobWorker(cfg, factory, service=ai)
    app = create_app(cfg, session_factory=factory, collector_factory=collector,
                     document_worker=document_worker, ai_analysis_worker=ai_worker)
    app.state.runner.run(TriggerType.CLI)
    key = ec.generate_private_key(ec.SECP256R1())
    verifier = SupabaseTokenVerifier(cfg.supabase_url)
    verifier.client.get_signing_key_from_jwt = lambda _: SimpleNamespace(key=key.public_key())
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    sellers = []
    with factory() as db:
        for i, amount in enumerate([900000, 100, None, 900000, 900000]):
            subject = f"00000000-0000-0000-0000-{i+1:012d}"
            seller = make_seller(db, name=["Strong", "Low turnover", "Incomplete", "MSE", "Startup"][i],
                terms="Desktop Computers", turnover=amount, owner_subject=subject)
            if i in (3, 4):
                revision = db.scalar(select(SellerRevision).where(SellerRevision.seller_id == seller.id,
                                                                 SellerRevision.is_active.is_(True)))
                db.add(SellerAttribute(revision_id=revision.id,
                    key="mse_status" if i == 3 else "startup_status", value_type="BOOLEAN", value_text="TRUE"))
                db.commit()
            sellers.append((seller.id, subject))
    errors = []
    executions = {"successful": 0, "errors": 0, "by_job": {}}
    class Capture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                errors.append({"timestamp": timestamp(), "logger": record.name,
                               "message": record.getMessage()[:1000]})
    capture = Capture()
    logging.getLogger().addHandler(capture)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(.1)
    if not server.started:
        raise RuntimeError("Staging server failed to start")
    def event(e):
        executions["errors" if e.exception else "successful"] += 1
        executions["by_job"][e.job_id] = executions["by_job"].get(e.job_id, 0) + 1
    app.state.scheduler._scheduler.add_listener(event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    durations, counters = {}, {"requests": 0, "successes": 0, "failures": 0}
    start, start_iso = time.monotonic(), timestamp()
    last_activity = start
    activity_gaps = []
    memory_start = rss()
    memory_peak = memory_start
    models = [DocumentJob, ExtractionJob, FieldExtractionJob, AIAnalysisJob]
    def sizes():
        return {"db": db_path.stat().st_size, "wal": Path(str(db_path) + "-wal").stat().st_size
                if Path(str(db_path) + "-wal").exists() else 0}
    initial_sizes = sizes()
    def timed(name, action):
        t = time.perf_counter()
        result = action()
        durations.setdefault(name, []).append((time.perf_counter() - t) * 1000)
        return result
    client = httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=30)
    def request(path, token=None, expected=200):
        headers = {"Authorization": "Bearer " + token} if token else {}
        r = timed(path, lambda: client.get(path, headers=headers))
        counters["requests"] += 1
        if r.status_code == expected:
            counters["successes"] += 1
        else:
            counters["failures"] += 1
            errors.append({"timestamp": timestamp(), "path": path, "status": r.status_code})
        return r
    routes = []
    for route in app.routes:
        if not hasattr(route, "dependant"):
            continue
        def dependencies(d):
            return [getattr(x.call, "__name__", "") for x in d.dependencies] + [
                n for x in d.dependencies for n in dependencies(x)]
        names = dependencies(route.dependant)
        kind = "public" if "get_current_user" not in names else (
            "authenticated seller" if "/portal/" in route.path or "/sellers" in route.path else "authenticated/operator")
        routes.append({"path": route.path, "methods": sorted(route.methods), "category": kind,
                       "dependencies": names})
    (out / "routes.json").write_text(json.dumps(routes, indent=2))
    cycle = 0
    try:
        with (out / "metrics.jsonl").open("a", encoding="utf-8") as metrics:
            while time.monotonic() - start < args.seconds:
                gap = time.monotonic() - last_activity
                activity_gaps.append(gap)
                if gap > 60:
                    errors.append({"timestamp": timestamp(), "message": "Active work interrupted",
                                   "gap_seconds": gap})
                    break
                if (out / "STOP").exists():
                    raise RuntimeError("Controlled soak stopped before completion; window is invalid")
                cycle += 1
                if not thread.is_alive() or not app.state.scheduler.running:
                    raise RuntimeError("Server or scheduler stopped during soak")
                with factory() as db:
                    reserve_sqlite_writer(db)
                    tender_ids = list(db.scalars(select(Tender.id).order_by(Tender.id)))
                    if cycle % 6 == 0:
                        generation["value"] += 1
                    enqueue_job(db, tender_ids[(cycle - 1) % len(tender_ids)], "MANUAL")
                    db.commit()
                    timed("status_verification", lambda: verify_statuses(db, now=utcnow()))
                    db.commit()
                    timed("matching", lambda: MatchingService(db).recalculate(now=utcnow()))
                    fingerprints = [timed("corpus", lambda tid=tid: build_corpus(db, tid))["fingerprint"]
                                    for tid in tender_ids]
                    for tid, fp in zip(tender_ids, fingerprints):
                        assert build_corpus(db, tid)["fingerprint"] == fp
                    db.rollback()
                request("/health")
                if cycle == 1:
                    request("/openapi.json")
                    request("/api/tenders", expected=401)
                    request("/api/tenders", token="forged-token", expected=401)
                for sid, subject in sellers:
                    now = datetime.now(timezone.utc)
                    token = jwt.encode({"sub": subject, "role": "authenticated", "aud": "authenticated",
                        "iss": verifier.issuer, "iat": now, "exp": now + timedelta(minutes=5)}, key,
                        algorithm="ES256", headers={"kid": "disposable-soak"})
                    request("/api/tenders", token)
                    request(f"/api/portal/sellers/{sid}/summary", token)
                    listing = request(f"/api/portal/sellers/{sid}/tenders", token).json()
                    if listing.get("items"):
                        request(f"/api/portal/sellers/{sid}/tenders/{listing['items'][0]['tender_id']}", token)
                    other = sellers[1 if sid == sellers[0][0] else 0][0]
                    request(f"/api/portal/sellers/{other}/summary", token, expected=403)
                with factory() as db:
                    counts = {m.__tablename__: dict(db.execute(select(m.status, func.count()).group_by(m.status)).all())
                              for m in models}
                    matches = dict(db.execute(select(SellerTenderMatch.match_status, func.count()).group_by(
                        SellerTenderMatch.match_status)).all())
                memory = rss()
                memory_peak = max(memory_peak, memory)
                snapshot = {"timestamp": timestamp(), "uptime_seconds": time.monotonic() - start,
                    "cycle": cycle, **counters, "memory_bytes": memory, "cpu_seconds": time.process_time(),
                    "sizes": sizes(), "jobs": counts, "matches": matches, "scheduler": executions.copy(),
                    "scheduler_running": app.state.scheduler.running, "errors": len(errors)}
                snapshot["recent_errors"] = errors[-5:]
                metrics.write(json.dumps(snapshot) + "\n")
                metrics.flush()
                last_activity = time.monotonic()
                (out / "latest.json").write_text(json.dumps(snapshot, indent=2))
                if cycle == 1 or cycle % 3 == 0:
                    print(json.dumps(snapshot), flush=True)
                # Useful work continues every 20 seconds; scheduler polls every five seconds.
                for _ in range(20):
                    if time.monotonic() - start >= args.seconds:
                        break
                    time.sleep(1)
            # Stop enqueueing, allow real workers to drain terminally before shutdown.
            drain = time.monotonic() + 60
            while time.monotonic() < drain:
                with factory() as db:
                    unresolved = sum(db.scalar(select(func.count()).select_from(m).where(
                        m.status.in_(["PENDING", "RETRY", "RUNNING"]))) for m in models)
                if not unresolved:
                    break
                time.sleep(1)
            elapsed = time.monotonic() - start
            final_gap = time.monotonic() - last_activity
            activity_gaps.append(final_gap)
            if final_gap > 60:
                errors.append({"timestamp": timestamp(), "message": "Active work interrupted before completion",
                               "gap_seconds": final_gap})
            with factory() as db:
                import sqlalchemy
                integrity = db.execute(sqlalchemy.text("PRAGMA integrity_check")).scalars().all()
                foreign_keys = db.execute(sqlalchemy.text("PRAGMA foreign_key_check")).all()
                job_counts = {m.__tablename__: dict(db.execute(select(m.status, func.count()).group_by(m.status)).all())
                              for m in models}
                attempts = {m.__tablename__: sum(db.scalars(select(m.attempt_count))) for m in models}
            stats = {}
            for name, values in durations.items():
                v = sorted(values)
                stats[name] = {"n": len(v), "median_ms": v[len(v)//2],
                    "p95_ms": v[min(len(v)-1, int(len(v)*.95))] if len(v) >= 20 else None, "max_ms": v[-1]}
            summary = {"start": start_iso, "end": timestamp(), "elapsed_seconds": elapsed,
                **counters, "cycles": cycle, "scheduler": executions, "jobs": job_counts,
                "attempts": attempts, "unresolved_jobs": unresolved, "crashes": 0, "restarts": 0,
                "errors": errors, "lock_errors": sum("locked" in str(e).lower() for e in errors),
                "memory_start": memory_start, "memory_peak": memory_peak, "memory_end": rss(),
                "cpu_seconds": time.process_time(), "sizes_start": initial_sizes, "sizes_end": sizes(),
                "maximum_activity_gap_seconds": max(activity_gaps),
                "integrity": integrity, "foreign_keys": [list(r) for r in foreign_keys], "performance": stats,
                "verdict": "PASS" if elapsed >= args.seconds and not errors and not unresolved
                    and integrity == ["ok"] and not foreign_keys else "FAIL"}
            (out / "summary.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps({k: v for k, v in summary.items() if k != "performance"}), flush=True)
    finally:
        server.should_exit = True
        thread.join(timeout=30)
        client.close()
        engine.dispose()
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
