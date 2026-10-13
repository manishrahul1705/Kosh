#!/usr/bin/env python
"""One-bid corpus inspection, annotation scan, optional acquisition and mock verification."""

import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.core.config import Settings
from app.database.session import build_engine, build_session_factory
from app.database.models import Tender
from app.corpus.service import build_corpus
from app.documents.documents_service import DocumentsService
from app.documents.references import ReferenceDiscovery
from app.corpus.queue import enqueue_corpus
from app.ai.job_worker import AIAnalysisJobWorker


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bid", required=True)
    p.add_argument(
        "--scan",
        action="store_true",
        help="Persist PDF annotation provenance; no downloads",
    )
    p.add_argument(
        "--acquire-references",
        action="store_true",
        help="Explicit live GeM acquisition for this bid only",
    )
    p.add_argument(
        "--refresh-references",
        action="store_true",
        help="With --acquire-references, refresh already acquired versions",
    )
    p.add_argument("--retry-failed", action="store_true")
    p.add_argument(
        "--mock-analysis",
        action="store_true",
        help="Queue and run exactly one offline mock corpus job",
    )
    args = p.parse_args()
    settings = Settings()
    if args.mock_analysis:
        settings = settings.model_copy(update={"ai_provider": "mock", "ai_model": ""})
    engine = build_engine(settings.resolved_database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as s:
            t = s.scalar(select(Tender).where(Tender.bid_number == args.bid))
            if t is None:
                p.error("Tender not found")
            tid = t.id
            if args.scan or args.acquire_references:
                ReferenceDiscovery(DocumentsService(settings)).run(
                    s,
                    t,
                    acquire=args.acquire_references,
                    retry_failed=args.retry_failed,
                    refresh_existing=args.refresh_references,
                )
            job = None
            if args.mock_analysis:
                result = enqueue_corpus(s, tid, settings, reason="MANUAL")
                s.commit()
                job = result.job_id
            corpus = build_corpus(s, tid)
        if job:
            worker = AIAnalysisJobWorker(settings, factory)
            batch = worker.run_batch(max_jobs=1, job_id=job)
            corpus["mock_result"] = [vars(j) for j in batch.jobs]
            worker.service.provider().close()
        print(json.dumps(corpus, ensure_ascii=False, indent=2, default=str))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
