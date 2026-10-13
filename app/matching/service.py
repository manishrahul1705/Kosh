"""Automatic seller <-> tender matching. Deterministic, with no LLM calls.

Each tender is analysed once (Stages 2-3: documents, fields, one AI corpus
analysis). The results are stored. This service then compares the stored
results with every seller profile:

    live tenders x sellers
        -> relevance (keyword/category, cheap, in memory)
        -> eligibility, for relevant pairs only (app.eligibility, rule-based,
           reuses an identical prior run)
        -> one SellerTenderMatch row per pair: MATCHED / NOT_MATCHED / REVIEW_REQUIRED,
           with explained reasons

A pair is recomputed only when the seller's active profile revision, the
tender's analysed state (fingerprint) or the matcher version changed. So a
periodic run does no work when nothing changed, and an interrupted run simply
resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.database.matching_models import SellerTenderMatch
from app.database.models import (
    AIAnalysisRun,
    DocumentVersion,
    EligibilityRequirementResult,
    EligibilityRun,
    Seller,
    SellerAttribute,
    SellerRevision,
    Tender,
    TenderDocument,
    TenderFieldExtraction,
    TenderStatusRecord,
)
from app.eligibility.engine import EligibilityEngine
from app.corpus.service import build_corpus
from app.database.session import reserve_sqlite_writer
from app.eligibility.service import EligibilityService
from app.matching.relevance import RELEVANCE_ATTRIBUTE_KEYS, evaluate_relevance, parse_terms
from app.services.status_service import CurrentStatus

logger = logging.getLogger("app.matching")

MATCHER_VERSION = "1.0.0"


class MatchStatus:
    MATCHED = "MATCHED"
    NOT_MATCHED = "NOT_MATCHED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


ACTIVE_TENDER_STATES = (CurrentStatus.LIVE.value, CurrentStatus.UPCOMING.value)

_PASS = {"PASS", "PASS_WITH_RELAXATION"}
_FAIL = {"FAIL"}
_REVIEW = {"REVIEW_REQUIRED", "INSUFFICIENT_INFORMATION", "CONDITIONALLY_PASS"}


def match_status_for(eligibility_status: str | None) -> str:
    """Unknown never becomes a failure: only a definitive NOT_ELIGIBLE is NOT_MATCHED."""
    if eligibility_status == "ELIGIBLE":
        return MatchStatus.MATCHED
    if eligibility_status == "NOT_ELIGIBLE":
        return MatchStatus.NOT_MATCHED
    return MatchStatus.REVIEW_REQUIRED


@dataclass
class MatchStats:
    tenders_considered: int = 0
    sellers_considered: int = 0
    evaluated: int = 0
    up_to_date: int = 0
    marked_not_relevant: int = 0
    errors: int = 0
    deferred: int = 0
    error_pairs: list[tuple[int, int]] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d.pop("error_pairs")
        return d


@dataclass(frozen=True)
class _SellerContext:
    seller_id: int
    revision_id: int
    terms: list[str]


class MatchingService:
    def __init__(self, db: Session):
        self.db = db

    # -- inputs --------------------------------------------------------------

    def _seller_contexts(self, seller_ids: list[int] | None) -> list[_SellerContext]:
        stmt = (select(SellerRevision)
                .join(Seller, Seller.id == SellerRevision.seller_id)
                .where(SellerRevision.is_active.is_(True)))
        if seller_ids is not None:
            stmt = stmt.where(SellerRevision.seller_id.in_(seller_ids))
        revisions = self.db.scalars(stmt.order_by(SellerRevision.seller_id, SellerRevision.revision_number.desc())).all()
        contexts: dict[int, _SellerContext] = {}
        for rev in revisions:
            if rev.seller_id in contexts:  # keep the highest active revision only
                continue
            raw = self.db.scalars(
                select(SellerAttribute).where(SellerAttribute.revision_id == rev.id,
                                              SellerAttribute.key.in_(RELEVANCE_ATTRIBUTE_KEYS))
            ).all()
            values = [a.value_json or a.value_text for a in raw]
            contexts[rev.seller_id] = _SellerContext(rev.seller_id, rev.id, parse_terms(values))
        return list(contexts.values())

    def _tender_fingerprints(self, tender_ids: list[int], tenders: dict[int, Tender]) -> dict[int, str]:
        if not tender_ids:
            return {}
        ai = dict(self.db.execute(
            select(AIAnalysisRun.tender_id, func.max(AIAnalysisRun.id))
            .where(AIAnalysisRun.tender_id.in_(tender_ids), AIAnalysisRun.analysis_scope == "TENDER_CORPUS",
                   AIAnalysisRun.is_current.is_(True))
            .group_by(AIAnalysisRun.tender_id)).all())
        fields = dict(self.db.execute(
            select(TenderFieldExtraction.tender_id, func.max(TenderFieldExtraction.id))
            .where(TenderFieldExtraction.tender_id.in_(tender_ids), TenderFieldExtraction.is_current.is_(True))
            .group_by(TenderFieldExtraction.tender_id)).all())
        docs = dict(self.db.execute(
            select(TenderDocument.tender_id, func.max(DocumentVersion.id))
            .join(DocumentVersion, DocumentVersion.document_id == TenderDocument.id)
            .where(TenderDocument.tender_id.in_(tender_ids))
            .group_by(TenderDocument.tender_id)).all())
        from app.corpus.analysis import CORPUS_PROMPT_VERSION
        engine_version = EligibilityEngine().engine_version
        out = {}
        for tid in tender_ids:
            raw = "|".join(str(x) for x in (tenders[tid].source_fingerprint, ai.get(tid), fields.get(tid),
                                            docs.get(tid), engine_version, MATCHER_VERSION, CORPUS_PROMPT_VERSION))
            out[tid] = hashlib.sha256(raw.encode()).hexdigest()
        return out

    # -- reasons -------------------------------------------------------------

    def _reasons(self, relevance, run: EligibilityRun) -> tuple[list[dict], int, int, int]:
        reasons: list[dict] = [{
            "kind": "MATCHED", "requirement": "Product / service relevance",
            "requirement_type": "RELEVANCE", "detail": relevance.reason,
        }]
        passed = failed = review = 0
        results = self.db.scalars(select(EligibilityRequirementResult)
                                  .where(EligibilityRequirementResult.run_id == run.id)
                                  .order_by(EligibilityRequirementResult.id)).all()
        for r in results:
            if r.status in _PASS:
                kind, passed = "MATCHED", passed + 1
            elif r.status in _FAIL:
                kind, failed = "FAILED", failed + 1
            elif r.status in _REVIEW:
                kind, review = "REVIEW", review + 1
            else:
                continue  # NOT_APPLICABLE: optional/informational, not a gate
            reasons.append({
                "kind": kind, "requirement": r.requirement_name, "requirement_type": r.requirement_type,
                "detail": r.reason or "", "requirement_status": r.status,
                "relaxation_applied": r.relaxation_applied,
                "ai_requirement_id": r.ai_requirement_id, "stage3b_field_id": r.stage3b_field_id,
            })
        if run.status == "ANALYSIS_INCOMPLETE":
            reasons.append({"kind": "REVIEW", "requirement": "Tender analysis",
                            "requirement_type": "ANALYSIS",
                            "detail": "Tender documents are not fully processed yet; result will update "
                                      "automatically when analysis completes."})
        elif run.status != "ELIGIBLE" and failed == 0 and review == 0:
            reasons.append({"kind": "REVIEW", "requirement": "Eligibility decision",
                            "requirement_type": "ELIGIBILITY",
                            "detail": f"Overall status {run.status}: {run.summary or ''}".strip()})
        return reasons, passed, failed, review

    # -- main ----------------------------------------------------------------

    def recalculate(self, *, now: datetime, seller_ids: list[int] | None = None,
                    tender_ids: list[int] | None = None, max_evaluations: int = 500) -> MatchStats:
        stats = MatchStats()
        reserve_sqlite_writer(self.db, renew_read=True)
        sellers = self._seller_contexts(seller_ids)
        stats.sellers_considered = len(sellers)
        if not sellers:
            return stats

        tstmt = (select(Tender).join(TenderStatusRecord, TenderStatusRecord.tender_id == Tender.id)
                 .where(TenderStatusRecord.current_status.in_(ACTIVE_TENDER_STATES)))
        if tender_ids is not None:
            tstmt = tstmt.where(Tender.id.in_(tender_ids))
        tenders = {t.id: t for t in self.db.scalars(tstmt.order_by(Tender.bid_end_at, Tender.id)).all()}
        stats.tenders_considered = len(tenders)
        if not tenders:
            return stats
        tender_list = list(tenders.values())
        fingerprints = self._tender_fingerprints(list(tenders), tenders)
        corpus_fingerprints = {}
        # Snapshot the plain values first: EligibilityService commits, which expires ORM objects.
        tender_text = {t.id: (t.category, t.title) for t in tender_list}

        for seller in sellers:
            reserve_sqlite_writer(self.db)
            existing = {m.tender_id: m for m in self.db.scalars(
                select(SellerTenderMatch).where(SellerTenderMatch.seller_id == seller.seller_id,
                                                SellerTenderMatch.tender_id.in_(list(tenders)))).all()}
            for tid in tenders:
                reserve_sqlite_writer(self.db)
                category, title = tender_text[tid]
                relevance = evaluate_relevance(seller.terms, category, title)
                row = existing.get(tid)
                fp = fingerprints[tid]
                if relevance.status != "RELEVANT":
                    if row is not None and row.relevance_status == "RELEVANT":
                        self._write(row, seller, tid, relevance, None, MatchStatus.NOT_MATCHED,
                                    [{"kind": "INFO", "requirement": "Product / service relevance",
                                      "requirement_type": "RELEVANCE", "detail": relevance.reason}],
                                    (0, 0, 0), fp, now)
                        self.db.commit()
                        stats.marked_not_relevant += 1
                    continue
                if tid not in corpus_fingerprints:
                    corpus_fingerprints[tid] = build_corpus(self.db, tid)["fingerprint"]
                fp = hashlib.sha256((fp + "|" + corpus_fingerprints[tid]).encode()).hexdigest()
                if (row is not None and row.seller_revision_id == seller.revision_id
                        and row.tender_state_fingerprint == fp and row.matcher_version == MATCHER_VERSION
                        and row.relevance_status == "RELEVANT"):
                    stats.up_to_date += 1
                    continue
                if stats.evaluated >= max_evaluations:
                    stats.deferred += 1
                    continue
                try:
                    run = EligibilityService(self.db).evaluate_tender(tid, seller.seller_id)  # commits
                    reserve_sqlite_writer(self.db)
                    reasons, p, f, r = self._reasons(relevance, run)
                    if row is None:
                        row = self.db.scalar(select(SellerTenderMatch).where(
                            SellerTenderMatch.seller_id == seller.seller_id, SellerTenderMatch.tender_id == tid))
                    if row is None:
                        row = SellerTenderMatch(seller_id=seller.seller_id, tender_id=tid, created_at=now)
                        self.db.add(row)
                    self._write(row, seller, tid, relevance, run, match_status_for(run.status), reasons,
                                (p, f, r), fp, now)
                    self.db.commit()
                    stats.evaluated += 1
                except Exception:
                    self.db.rollback()
                    stats.errors += 1
                    stats.error_pairs.append((seller.seller_id, tid))
                    logger.exception("match_evaluation_failed seller_id=%s tender_id=%s", seller.seller_id, tid)
        log_event(logger, logging.INFO, "matching_done", **stats.as_dict())
        self.db.commit()
        return stats

    @staticmethod
    def _write(row: SellerTenderMatch, seller: _SellerContext, tender_id: int, relevance, run,
               status: str, reasons: list[dict], counts: tuple[int, int, int], fp: str, now: datetime) -> None:
        row.seller_id = seller.seller_id
        row.tender_id = tender_id
        row.seller_revision_id = seller.revision_id
        row.eligibility_run_id = run.id if run is not None else None
        row.eligibility_status = run.status if run is not None else None
        row.relevance_status = relevance.status
        row.match_status = status
        row.matched_terms_json = json.dumps(relevance.matched_terms)
        row.reasons_json = json.dumps(reasons)
        row.passed_count, row.failed_count, row.review_count = counts
        row.tender_state_fingerprint = fp
        row.matcher_version = MATCHER_VERSION
        row.computed_at = now
        row.updated_at = now
