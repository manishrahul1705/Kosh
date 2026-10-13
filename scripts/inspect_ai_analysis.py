#!/usr/bin/env python
"""Read-only inspection of Stage 3C AI analyses (never writes, never calls a provider).

    python scripts/inspect_ai_analysis.py --list
    python scripts/inspect_ai_analysis.py --stage3b-extraction-id 1                # summary + metadata
    python scripts/inspect_ai_analysis.py --stage3b-extraction-id 1 --requirements [--level MANDATORY]
    python scripts/inspect_ai_analysis.py --stage3b-extraction-id 1 --evidence [--requirement 3]
    python scripts/inspect_ai_analysis.py --stage3b-extraction-id 1 --flags
    python scripts/inspect_ai_analysis.py --stage3b-extraction-id 1 --chunks
    python scripts/inspect_ai_analysis.py --stage3b-extraction-id 1 --history
    python scripts/inspect_ai_analysis.py --stage3b-extraction-id 1 --verify-sources
    python scripts/inspect_ai_analysis.py --analysis-id 2
    python scripts/inspect_ai_analysis.py --bid GEM/2026/B/8124821
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.database.models import (  # noqa: E402
    AIAnalysisFlag,
    AIAnalysisJob,
    AIAnalysisRun,
    AIEvidenceChunk,
    AIRequirement,
    AIRequirementEvidence,
    DocumentVersion,
    TenderFieldExtraction,
)
from app.database.session import build_engine, build_session_factory  # noqa: E402
from app.extraction.constants import ExtractionError  # noqa: E402
from app.extraction.storage import hash_file, resolve_source_path  # noqa: E402
from app.services.integrity import stage3a_digest, stage3b_digest  # noqa: E402
from app.utils.bid_number import InvalidBidNumber, normalize_bid_number  # noqa: E402


def show_list(s) -> None:
    print(f"{'stage3b_id':>10}  {'bid_number':<22} {'document':<12} {'3B status':<16} stage3c")
    for r in s.scalars(select(TenderFieldExtraction).order_by(TenderFieldExtraction.id)):
        runs = s.scalars(select(AIAnalysisRun).where(AIAnalysisRun.stage3b_extraction_id == r.id,
                                                     AIAnalysisRun.is_current.is_(True))
                         .order_by(AIAnalysisRun.id.desc())).all()
        if runs:
            state = "; ".join(f"{a.status} (analysis_id {a.id}, {a.provider}/{a.model}; {a.requirements_count} req, "
                              f"{a.flags_count} flags)" for a in runs)
        else:
            j = s.scalar(select(AIAnalysisJob).where(AIAnalysisJob.stage3b_extraction_id == r.id)
                         .order_by(AIAnalysisJob.id.desc()).limit(1))
            state = f"job {j.id} {j.status}{' ' + j.error_code if j.error_code else ''}" if j else "-"
        print(f"{r.id:>10}  {r.bid_number:<22} {r.document_type + ' v' + str(r.version_number):<12} "
              f"{r.status + ('' if r.is_current else ' (old)'):<16} {state}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Inspect Stage 3C AI analyses (read-only)")
    p.add_argument("--list", action="store_true")
    p.add_argument("--stage3b-extraction-id", type=int)
    p.add_argument("--analysis-id", type=int)
    p.add_argument("--bid")
    p.add_argument("--requirements", action="store_true")
    p.add_argument("--level", help="with --requirements: MANDATORY | OPTIONAL | CONDITIONAL | INFORMATIONAL | UNKNOWN")
    p.add_argument("--evidence", action="store_true")
    p.add_argument("--requirement", type=int, help="with --evidence: requirement sequence number")
    p.add_argument("--flags", action="store_true")
    p.add_argument("--chunks", action="store_true")
    p.add_argument("--history", action="store_true")
    p.add_argument("--verify-sources", action="store_true")
    a = p.parse_args(argv)
    settings = Settings()
    engine = build_engine(settings.resolved_database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as s:
            if a.list:
                show_list(s)
                return 0
            run = None
            if a.analysis_id:
                run = s.get(AIAnalysisRun, a.analysis_id)
            elif a.stage3b_extraction_id:
                run = s.scalar(select(AIAnalysisRun).where(
                    AIAnalysisRun.stage3b_extraction_id == a.stage3b_extraction_id,
                    AIAnalysisRun.is_current.is_(True)).order_by(AIAnalysisRun.id.desc()).limit(1))
            elif a.bid:
                try:
                    bid = normalize_bid_number(a.bid)
                except InvalidBidNumber as exc:
                    print(f"Invalid bid number: {exc}")
                    return 2
                run = s.scalar(select(AIAnalysisRun).where(AIAnalysisRun.bid_number == bid,
                                                           AIAnalysisRun.is_current.is_(True))
                               .order_by(AIAnalysisRun.version_number.desc(), AIAnalysisRun.id.desc()).limit(1))
            else:
                p.print_help()
                return 2
            s3b_id = run.stage3b_extraction_id if run else a.stage3b_extraction_id
            if a.verify_sources and s3b_id:
                fx = s.get(TenderFieldExtraction, s3b_id)
                if fx is None:
                    print(f"Stage 3B extraction {s3b_id} not found.")
                    return 0
                v = s.get(DocumentVersion, fx.document_version_id)
                print("Source immutability check (read-only):")
                print(f"  Stage 3A extraction {fx.stage3a_extraction_id} row digest: "
                      f"{stage3a_digest(s, fx.stage3a_extraction_id)}")
                print(f"  Stage 3B extraction {fx.id} row digest:  {stage3b_digest(s, fx.id)}")
                print(f"  DocumentVersion {v.id}: v{v.version_number} sha256={v.sha256}")
                try:
                    sha, size = hash_file(resolve_source_path(settings.resolved_document_storage_path, v.storage_path))
                    print(f"  PDF on disk:   sha256={sha} size={size}")
                    print(f"  PDF MATCH:     {'YES' if sha == v.sha256 else 'NO'}")
                except ExtractionError as exc:
                    print(f"  PDF check: {exc}")
                print("  (identical digests before and after Stage 3C => Stage 3A/3B rows untouched)")
                return 0
            if run is None:
                print("No current Stage 3C analysis found.")
                return 0

            print(f"Tender:      {run.bid_number}")
            print(f"Document:    {run.document_type} v{run.version_number}   (document_version_id "
                  f"{run.document_version_id}, Stage 3A {run.stage3a_extraction_id}, Stage 3B "
                  f"{run.stage3b_extraction_id})")
            print(f"Analysis {run.id}: {run.status}{' (' + run.status_code + ')' if run.status_code else ''}  "
                  f"current={run.is_current}")
            print(f"Provider:    {run.provider}   Model: {run.model}")
            print(f"Versions:    prompt={run.prompt_version} schema={run.schema_version} chunker={run.chunker_version}")
            print(f"Evidence:    {run.chunks_sent}/{run.chunks_total} chunks sent, {run.input_characters} characters,"
                  f" request sha256={run.request_sha256[:16]}...")
            print(f"Usage:       tokens in={run.input_tokens} out={run.output_tokens} total={run.total_tokens}, "
                  f"latency={run.latency_ms} ms, provider attempts={run.provider_attempts}")
            print(f"Result:      {run.requirements_count} requirements | {run.rejected_count} rejected | "
                  f"{run.flags_count} flags | {run.ambiguities_count} ambiguities | {run.conflicts_count} conflicts")
            print(f"\nSummary: {run.summary}")
            print("(Interpretation only - Stage 3B values stay authoritative; no seller eligibility is assessed.)")

            reqs = s.scalars(select(AIRequirement).where(AIRequirement.analysis_run_id == run.id)
                             .order_by(AIRequirement.sequence)).all()
            if a.requirements:
                shown = [q for q in reqs if not a.level or q.obligation_level == a.level.upper()]
                print(f"\n----- Requirements ({len(shown)}) -----")
                for q in shown:
                    val = f" value={q.value_text}{' ' + q.unit if q.unit else ''}" if q.value_text else ""
                    risk = f" risks={json.loads(q.risk_flags_json)}" if q.risk_flags_json else ""
                    adj = f" (model said {q.model_obligation_level}; {q.level_adjustment})" if q.level_adjustment else ""
                    print(f"  #{q.sequence} [{q.obligation_level}{adj}] {q.requirement_type}/{q.category} "
                          f"applies_to={q.applies_to}{' ATC' if q.is_buyer_atc else ''}{val}{risk}")
                    print(f"      {q.title[:150]}")
                    if q.condition_text:
                        print(f"      condition: {q.condition_text[:150]}")
                    if q.ambiguity:
                        print(f"      ambiguity: {q.ambiguity[:150]}")
            if a.evidence:
                by_seq = {q.id: q.sequence for q in reqs}
                stmt = select(AIRequirementEvidence).where(AIRequirementEvidence.analysis_run_id == run.id)
                rows = [e for e in s.scalars(stmt.order_by(AIRequirementEvidence.id))
                        if a.requirement is None or by_seq.get(e.requirement_id) == a.requirement]
                print(f"\n----- Evidence ({len(rows)}) -----")
                for e in rows:
                    print(f"  requirement #{by_seq.get(e.requirement_id)} <- {e.chunk_key} (page {e.page_number}, "
                          f"section '{e.section_heading}')")
                    print(f"      quote: {e.quote[:200]!r}")
            if a.flags:
                flags = s.scalars(select(AIAnalysisFlag).where(AIAnalysisFlag.analysis_run_id == run.id)
                                  .order_by(AIAnalysisFlag.id)).all()
                by_seq = {q.id: q.sequence for q in reqs}
                print(f"\n----- Flags ({len(flags)}) -----")
                for f in flags:
                    ref = f" req #{by_seq.get(f.requirement_id)}" if f.requirement_id else ""
                    s3b = f" stage3b {f.stage3b_field_name}={f.stage3b_value}" if f.stage3b_field_name else ""
                    print(f"  [{f.severity}] {f.flag_type}{ref}{s3b}: {f.message[:200]}")
            if a.chunks:
                chunks = s.scalars(select(AIEvidenceChunk).where(AIEvidenceChunk.analysis_run_id == run.id)
                                   .order_by(AIEvidenceChunk.sequence)).all()
                print(f"\n----- Chunks ({len(chunks)}) -----")
                for c in chunks:
                    sent = "sent" if c.sent else f"NOT sent ({c.exclusion_reason})"
                    print(f"  {c.chunk_key} {c.kind}/{c.source_type} page {c.page_number}"
                          f"{'-' + str(c.page_end) if c.page_end != c.page_number else ''} "
                          f"'{c.section_heading or '-'}' {c.char_count} chars, {sent}")
            if a.history:
                hist = s.scalars(select(AIAnalysisRun).where(
                    AIAnalysisRun.stage3b_extraction_id == run.stage3b_extraction_id).order_by(AIAnalysisRun.id)).all()
                print(f"\n----- History ({len(hist)}) -----")
                for h in hist:
                    print(f"  analysis {h.id}: {h.status} current={h.is_current} {h.provider}/{h.model} "
                          f"{h.prompt_version}/{h.schema_version} req={h.requirements_count} created={h.created_at}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
