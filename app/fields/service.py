"""Stage 3B service: Stage 3A extraction -> persisted tender field extraction.

  prepare(id)        one short read-only session (load Stage 3A rows + checks) ->
                     session closed -> rule engine in memory (no DB transaction held).
  persist(session)   adds run + values (ALL registry fields) + evidence to the
                     caller's transaction (the worker also finishes its job there).
Stage 3A rows are only read; Stage 2 files are never opened.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.job_queue import queue_after_stage3b_commit
from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import TenderFieldEvidence, TenderFieldExtraction, TenderFieldValue
from app.fields.constants import (
    FIELD_EXTRACTOR_NAME,
    FIELD_EXTRACTOR_VERSION,
    USABLE_STAGE3A_STATUSES,
    FieldErrorCode,
    FieldStatus,
    RunStatus,
)
from app.fields.engine import EngineOutput, run_engine
from app.fields.evidence import Source, load_source
from app.fields.normalizers import Normalized
from app.utils.dates import utcnow

logger = logging.getLogger("app.fields.service")

ALREADY = "ALREADY_EXTRACTED"
EXTRACTED = "EXTRACTED"
NOT_READY = "NOT_READY"
ERROR = "ERROR"


@dataclass
class PreparedFields:
    stage3a_extraction_id: int
    force: bool
    source: Source | None = None
    already_id: int | None = None
    not_ready_code: str | None = None
    not_ready_message: str | None = None
    output: EngineOutput | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    status: str | None = None
    status_code: str | None = None


@dataclass
class FieldOutcome:
    outcome: str                         # EXTRACTED | ALREADY_EXTRACTED | NOT_READY | ERROR
    stage3a_extraction_id: int
    field_extraction_id: int | None = None
    status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    fields_resolved: int = 0
    fields_unknown: int = 0
    fields_conflict: int = 0


def current_field_extraction_id(session: Session, stage3a_extraction_id: int,
                                extractor_version: str = FIELD_EXTRACTOR_VERSION) -> int | None:
    return session.scalar(select(TenderFieldExtraction.id).where(
        TenderFieldExtraction.stage3a_extraction_id == stage3a_extraction_id,
        TenderFieldExtraction.extractor_version == extractor_version,
        TenderFieldExtraction.is_current.is_(True)).limit(1))


def stage3a_usable(src: Source) -> tuple[str, str] | None:
    """None when usable, else (error_code, message)."""
    if not src.stage3a_is_current:
        return (FieldErrorCode.STAGE3A_SUPERSEDED.value,
                f"Stage 3A extraction {src.stage3a_extraction_id} is not current (superseded)")
    if src.stage3a_status not in USABLE_STAGE3A_STATUSES:
        return (FieldErrorCode.STAGE3A_NOT_USABLE.value,
                f"Stage 3A extraction status {src.stage3a_status} has no usable text/tables")
    return None


class FieldExtractionService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session],
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.clock = clock

    def prepare(self, stage3a_extraction_id: int, force: bool = False) -> PreparedFields:
        p = PreparedFields(stage3a_extraction_id, force)
        with self.session_factory() as s:
            src = load_source(s, stage3a_extraction_id)
            existing = current_field_extraction_id(s, stage3a_extraction_id) if src else None
            s.rollback()  # read-only; release the snapshot before rule evaluation
        if src is None:
            p.not_ready_code = FieldErrorCode.STAGE3A_NOT_FOUND.value
            p.not_ready_message = f"Stage 3A extraction {stage3a_extraction_id} not found"
            return p
        p.source = src
        bad = stage3a_usable(src)
        if bad:
            p.not_ready_code, p.not_ready_message = bad
            return p
        if existing is not None and not force:
            p.already_id = existing
            return p
        p.started_at, t0 = self.clock(), time.monotonic()
        p.output = run_engine(src, self.settings.field_extraction_document_timezone)
        p.completed_at, p.duration_ms = self.clock(), int((time.monotonic() - t0) * 1000)
        out = p.output
        if out.conflicts:
            p.status, p.status_code = RunStatus.PARTIAL_SUCCESS.value, FieldErrorCode.FIELD_CONFLICTS.value
        elif src.stage3a_status != "SUCCESS":
            p.status, p.status_code = RunStatus.PARTIAL_SUCCESS.value, FieldErrorCode.STAGE3A_PARTIAL.value
        elif not any(r.status == FieldStatus.RESOLVED.value and r.spec.group != "IDENTITY" for r in out.results):
            p.status, p.status_code = RunStatus.PARTIAL_SUCCESS.value, FieldErrorCode.NO_FIELDS_FOUND.value
        else:
            p.status = RunStatus.SUCCESS.value
        log_event(logger, logging.INFO if p.status == RunStatus.SUCCESS.value else logging.WARNING,
                  "field_extraction_completed", stage3a_extraction_id=stage3a_extraction_id, bid=src.bid_number,
                  status=p.status, resolved=out.resolved, unknown=out.unknown, conflicts=out.conflicts,
                  candidates=out.candidates_total, duration_ms=p.duration_ms)
        return p

    def persist(self, session: Session, p: PreparedFields) -> int:
        """Add run + values + evidence to the caller's transaction (no commit)."""
        src, out = p.source, p.output
        assert src is not None and out is not None
        now = self.clock()
        if p.force:
            session.execute(update(TenderFieldExtraction)
                            .where(TenderFieldExtraction.stage3a_extraction_id == src.stage3a_extraction_id,
                                   TenderFieldExtraction.extractor_version == FIELD_EXTRACTOR_VERSION,
                                   TenderFieldExtraction.is_current.is_(True))
                            .values(is_current=False, updated_at=now)
                            .execution_options(synchronize_session=False))
        run = TenderFieldExtraction(
            stage3a_extraction_id=src.stage3a_extraction_id, document_version_id=src.document_version_id,
            document_id=src.document_id, tender_id=src.tender_id, bid_number=src.bid_number,
            document_type=src.document_type, version_number=src.version_number,
            extractor_name=FIELD_EXTRACTOR_NAME, extractor_version=FIELD_EXTRACTOR_VERSION, status=p.status,
            is_current=True, fields_total=len(out.results), fields_resolved=out.resolved,
            fields_unknown=out.unknown, fields_conflict=out.conflicts, candidates_total=out.candidates_total,
            duration_ms=p.duration_ms, error_code=p.status_code, started_at=p.started_at,
            completed_at=p.completed_at, created_at=now, updated_at=now)
        session.add(run)
        session.flush()
        values = []
        for r in out.results:
            sel = r.selected if r.status == FieldStatus.RESOLVED.value else None
            values.append(TenderFieldValue(
                field_extraction_id=run.id, tender_id=src.tender_id, field_name=r.spec.name,
                field_group=r.spec.group, value_type=r.spec.value_type, status=r.status, reason=r.reason,
                tri_state=r.tri_state, value_text=sel.text if sel else None, value_number=sel.number if sel else None,
                value_json=r.value_json(), unit=sel.unit if sel else None, evidence_strength=r.strength,
                candidate_count=len(r.candidates), created_at=now))
        session.add_all(values)
        session.flush()
        evidence = []
        for r, v in zip(out.results, values):
            for c, disp in zip(r.candidates, r.dispositions):
                norm = (json.dumps(c.result.value, ensure_ascii=False, sort_keys=True)
                        if isinstance(c.result, Normalized) else json.dumps({"rejected": c.result.reason}))
                if c.source_location:
                    norm=json.dumps({'value':json.loads(norm),'source_location':c.source_location},ensure_ascii=False,sort_keys=True)
                evidence.append(TenderFieldEvidence(
                    field_value_id=v.id, field_extraction_id=run.id, field_name=r.spec.name,
                    stage3a_extraction_id=src.stage3a_extraction_id, document_version_id=src.document_version_id,
                    page_number=c.page_number or None, table_id=c.table_id, table_index=c.table_index,
                    row_index=c.row_index, section_id=c.section_id, section_heading=c.section_heading,
                    evidence_type=c.evidence_type, strength=c.strength, rule=c.rule, source_label=c.source_label,
                    raw_value=c.raw_value, source_text=c.source_text, normalized_json=norm,
                    value_key=(c.result.key[:255] if isinstance(c.result, Normalized) else None),
                    disposition=disp, created_at=now))
        session.add_all(evidence)
        session.flush()
        return run.id

    def extract(self, stage3a_extraction_id: int, force: bool = False) -> FieldOutcome:
        """prepare + persist + commit (CLI/tests; the worker finishes its job atomically instead)."""
        p = self.prepare(stage3a_extraction_id, force)
        if p.not_ready_code:
            return FieldOutcome(NOT_READY, stage3a_extraction_id, error_code=p.not_ready_code,
                                error_message=p.not_ready_message)
        if p.already_id is not None:
            return self.outcome_for_existing(stage3a_extraction_id, p.already_id)
        with self.session_factory() as s:
            try:
                from app.database.session import reserve_sqlite_writer
                reserve_sqlite_writer(s)
                run_id = self.persist(s, p)
                s.commit()
                # Stage 3C: queue only, in its own commit; never rolls back Stage 3B
                queue_after_stage3b_commit(s, run_id, self.settings)
            except IntegrityError:
                s.rollback()
                return self.outcome_for_existing(stage3a_extraction_id,
                                                 current_field_extraction_id(s, stage3a_extraction_id))
            except OperationalError as exc:
                s.rollback()
                return FieldOutcome(ERROR, stage3a_extraction_id, error_code=FieldErrorCode.DATABASE_ERROR.value,
                                    error_message=str(exc)[:500], retryable=True)
        o = p.output
        return FieldOutcome(EXTRACTED, stage3a_extraction_id, run_id, p.status, p.status_code, None, False,
                            o.resolved, o.unknown, o.conflicts)

    def outcome_for_existing(self, stage3a_extraction_id: int, run_id: int | None) -> FieldOutcome:
        with self.session_factory() as s:
            r = s.get(TenderFieldExtraction, run_id) if run_id else None
            if r is None:
                return FieldOutcome(ALREADY, stage3a_extraction_id, run_id)
            return FieldOutcome(ALREADY, stage3a_extraction_id, r.id, r.status, r.error_code, None, False,
                                r.fields_resolved, r.fields_unknown, r.fields_conflict)
