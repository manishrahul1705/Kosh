"""Stage 3C service: Stage 3B run (+ its Stage 3A rows) -> persisted AI interpretation.

    prepare(id)    one short read-only session: load Stage 3B run + values and the
                   Stage 3A rows, checks, chunking, prompt. Session closed.
    call(p)        provider call(s) - NO database transaction held. Bounded
                   immediate retries for transient errors only.
    interpret(..)  strict parsing + grounding validation + deterministic flags.
    persist(s, ..) adds run + chunks + requirements + evidence + flags to the
                   caller's transaction (the worker also finishes its job there).

Stage 3A rows, Stage 3B rows and Stage 2 files are only read, never changed.
No credential is ever logged or persisted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.chunker import ChunkSet, build_chunks, select_chunks
from app.ai.constants import (
    ANALYZER_NAME,
    CHUNK_PRIORITY,
    CHUNKER_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    USABLE_STAGE3B_STATUSES,
    AIErrorCode,
    FlagType,
    RunStatus,
    Severity,
)
from app.ai.flags import FlagDraft, Stage3BValue, build_flags
from app.ai.grounding import GroundedOutput, ground
from app.ai.prompt import SYSTEM_PROMPT, BuiltPrompt, build_prompt, context_block
from app.ai.providers import build_provider, effective_model, effective_provider
from app.ai.providers.base import (
    AIProvider,
    AIRequest,
    AIResponse,
    DailyLimitReached,
    ProviderError,
    ProviderUnavailable,
)
from app.ai.redact import redact
from app.ai.schema import ResponseInvalid, parse_envelope
from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import (
    AIAnalysisFlag,
    AIAnalysisRun,
    AIEvidenceChunk,
    AIProviderCall,
    AIRequirement,
    AIRequirementEvidence,
    TenderFieldExtraction,
    TenderFieldValue,
)
from app.fields.constants import USABLE_STAGE3A_STATUSES
from app.fields.evidence import Source, load_source
from app.utils.dates import utcnow

logger = logging.getLogger("app.ai.service")

ANALYZED = "ANALYZED"
ALREADY = "ALREADY_ANALYZED"
NOT_READY = "NOT_READY"
PROVIDER_FAILED = "PROVIDER_FAILED"
RESPONSE_INVALID = "RESPONSE_INVALID"
ERROR = "ERROR"


@dataclass
class PreparedAnalysis:
    stage3b_extraction_id: int
    force: bool
    provider: str
    model: str
    not_ready_code: str | None = None
    not_ready_message: str | None = None
    already_id: int | None = None
    source: Source | None = None
    stage3b: dict[str, Stage3BValue] = field(default_factory=dict)
    chunks: ChunkSet | None = None
    prompt: BuiltPrompt | None = None
    corpus: dict | None = None
    input_coverage: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    chunk_sources: dict = field(default_factory=dict)
    source_fields: dict = field(default_factory=dict)


@dataclass
class CallResult:
    response: AIResponse | None = None
    error: ProviderError | None = None
    attempts: int = 0
    latency_ms: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class Interpretation:
    grounded: GroundedOutput
    flags: list[FlagDraft]
    status: str
    status_code: str | None


@dataclass
class AnalysisOutcome:
    outcome: str        # ANALYZED | ALREADY_ANALYZED | NOT_READY | PROVIDER_FAILED | RESPONSE_INVALID | ERROR
    stage3b_extraction_id: int
    analysis_run_id: int | None = None
    status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    transient: bool = False
    blocking: bool = False
    requirements: int = 0
    flags: int = 0


def current_analysis_id(session: Session, stage3b_extraction_id: int, provider: str, model: str) -> int | None:
    return session.scalar(select(AIAnalysisRun.id).where(
        AIAnalysisRun.analysis_scope == 'DOCUMENT', AIAnalysisRun.stage3b_extraction_id == stage3b_extraction_id, AIAnalysisRun.provider == provider,
        AIAnalysisRun.model == model, AIAnalysisRun.prompt_version == PROMPT_VERSION,
        AIAnalysisRun.schema_version == SCHEMA_VERSION, AIAnalysisRun.is_current.is_(True)).limit(1))


def provider_calls_last_24h(session: Session, now: datetime) -> int:
    """Provider call attempts recorded in the last 24 h (every attempt counts, incl. retries)."""
    return int(session.scalar(select(func.count()).select_from(AIProviderCall)
                              .where(AIProviderCall.started_at >= now - timedelta(hours=24))) or 0)


def load_stage3b_values(session: Session, field_extraction_id: int) -> dict[str, Stage3BValue]:
    rows = session.execute(select(TenderFieldValue.field_name, TenderFieldValue.status, TenderFieldValue.tri_state,
                                  TenderFieldValue.value_text, TenderFieldValue.value_number, TenderFieldValue.unit,
                                  TenderFieldValue.evidence_strength, TenderFieldValue.field_group)
                           .where(TenderFieldValue.field_extraction_id == field_extraction_id)).all()
    return {r.field_name: Stage3BValue(r.field_name, r.status, r.tri_state, r.value_text, r.value_number, r.unit,
                                       r.evidence_strength) for r in rows}


def _facts(values: dict[str, Stage3BValue]) -> tuple[list[dict], list[str]]:
    skip = {"bid_number", "document_version_id", "document_type", "document_version_number", "consignee_details",
            "buyer_added_atc_clauses"}
    facts, unresolved = [], []
    for name, v in values.items():
        if name in skip:
            continue
        if v.status == "RESOLVED":
            facts.append({"field": name, "value": (v.value_text or "")[:200]})
        elif v.status == "UNKNOWN":
            unresolved.append(name)
    return facts, unresolved


class AnalysisService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session], *,
                 provider_factory: Callable[[], AIProvider] | None = None,
                 clock: Callable[[], datetime] = utcnow, sleep: Callable[[float], None] = time.sleep) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.provider_factory = provider_factory or (lambda: build_provider(settings))
        self.clock = clock
        self.sleep = sleep
        self._provider: AIProvider | None = None

    # ------------------------------------------------------------------
    def provider(self) -> AIProvider:
        """Built lazily; raises NotConfigured / ProviderConfigError (blocking)."""
        if self._provider is None:
            self._provider = self.provider_factory()
        return self._provider

    def identity(self) -> tuple[str, str]:
        """(provider, model) used for idempotency - from the provider if it can be built."""
        try:
            p = self.provider()
            return p.name, p.model
        except ProviderError:
            return effective_provider(self.settings), effective_model(self.settings)

    # ------------------------------------------------------------------
    def prepare(self, stage3b_extraction_id: int, force: bool = False) -> PreparedAnalysis:
        provider, model = self.identity()
        p = PreparedAnalysis(stage3b_extraction_id, force, provider, model)
        with self.session_factory() as s:
            run = s.get(TenderFieldExtraction, stage3b_extraction_id)
            src = load_source(s, run.stage3a_extraction_id) if run is not None else None
            values = load_stage3b_values(s, run.id) if run is not None else {}
            existing = current_analysis_id(s, stage3b_extraction_id, provider, model) if run is not None else None
            run_current = bool(run.is_current) if run is not None else False
            run_status = run.status if run is not None else None
            s.rollback()  # read-only; release the snapshot before chunking / provider calls
        if run is None:
            p.not_ready_code = AIErrorCode.STAGE3B_NOT_FOUND.value
            p.not_ready_message = f"Stage 3B field extraction {stage3b_extraction_id} not found"
            return p
        if not run_current:
            p.not_ready_code = AIErrorCode.STAGE3B_NOT_CURRENT.value
            p.not_ready_message = f"Stage 3B field extraction {stage3b_extraction_id} is not current (superseded)"
            return p
        if run_status not in USABLE_STAGE3B_STATUSES:
            p.not_ready_code = AIErrorCode.STAGE3B_NOT_USABLE.value
            p.not_ready_message = f"Stage 3B status {run_status} is not usable"
            return p
        if src is None or not src.stage3a_is_current or src.stage3a_status not in USABLE_STAGE3A_STATUSES:
            p.not_ready_code = AIErrorCode.STAGE3A_NOT_USABLE.value
            p.not_ready_message = "Stage 3A extraction behind this Stage 3B run is missing, superseded or unusable"
            return p
        if existing is not None and not force:
            p.already_id = existing
            return p
        p.source, p.stage3b = src, values
        facts, unresolved = _facts(values)
        limit = self.settings.ai_max_input_characters
        budget = max(0, limit - len(SYSTEM_PROMPT) - context_block(facts, unresolved))
        chunks = build_chunks(src, max_chunk_chars=self.settings.ai_max_chunk_characters)
        p.chunks = select_chunks(chunks, max_chunks=self.settings.ai_max_chunks_per_analysis, max_chars=budget,
                                 include_boilerplate=self.settings.ai_include_boilerplate)
        while True:
            if not p.chunks.sent:
                p.prompt = None
                p.not_ready_code = AIErrorCode.NO_EVIDENCE_CHUNKS.value
                p.not_ready_message = ("No evidence chunk fits AI_MAX_INPUT_CHARACTERS" if chunks else
                                       "No evidence text could be built from the Stage 3A rows")
                return p
            p.prompt = build_prompt(bid_number=src.bid_number, document_type=src.document_type,
                                    version_number=src.version_number, chunks=p.chunks.sent, facts=facts,
                                    unresolved=unresolved)
            if p.prompt.characters <= limit:
                return p
            # JSON escaping / per-chunk overhead pushed the prompt over the limit:
            # drop the lowest-priority chunk that was going to be sent, then rebuild.
            victim = max(p.chunks.sent, key=lambda c: (CHUNK_PRIORITY.get(c.kind, 9), c.sequence))
            victim.sent, victim.exclusion_reason = False, "CHAR_LIMIT"

    # ------------------------------------------------------------------
    def call(self, p: PreparedAnalysis, *, job_id: int | None = None) -> CallResult:
        """Provider call with bounded retries for TRANSIENT failures only.

        Every attempt is recorded in ``ai_provider_calls`` (metadata only, short separate
        transaction AFTER the HTTP call - nothing is held open during it) and counts
        towards AI_MAX_ANALYSES_PER_DAY; a retry is not attempted once the cap is reached.
        """
        res = CallResult(started_at=self.clock())
        t0 = time.monotonic()
        try:
            provider = self.provider()
        except ProviderError as exc:
            res.error, res.completed_at = exc, self.clock()
            return res
        request = AIRequest(system=p.prompt.system, user=p.prompt.user,
                            max_output_tokens=self.settings.ai_max_output_tokens,
                            temperature=self.settings.ai_temperature,
                            timeout_seconds=self.settings.ai_request_timeout_seconds,
                            chunks=p.prompt.chunk_payload)
        max_attempts = 1 + self.settings.ai_max_retries
        secret = self.settings.ai_api_key_value()
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                with self.session_factory() as s:
                    used = provider_calls_last_24h(s, self.clock())
                if used >= self.settings.ai_max_analyses_per_day:
                    res.error = DailyLimitReached(f"{used} provider call(s) in the last 24 h")
                    break
            res.attempts = attempt
            started, a0 = self.clock(), time.monotonic()
            try:
                res.response, res.error = provider.generate(request), None
                status = "OK"
            except ProviderError as exc:
                res.response, res.error, status = None, exc, exc.code
            except Exception as exc:  # unexpected provider/library error: transient, bounded
                res.response = None
                res.error = ProviderUnavailable(redact(f"{type(exc).__name__}: {exc}", secret, limit=300))
                status = "PROVIDER_UNAVAILABLE"
            r = res.response
            duration = int((time.monotonic() - a0) * 1000)
            self._record_call(job_id, p, provider, attempt, status, duration, r, started)
            log_event(logger, logging.INFO if status == "OK" else logging.WARNING, "ai_provider_call",
                      provider=provider.name, model=provider.model, stage3b_extraction_id=p.stage3b_extraction_id,
                      job_id=job_id, attempt=attempt, duration_ms=duration, status=status,
                      input_tokens=r.input_tokens if r else None, output_tokens=r.output_tokens if r else None,
                      error=redact(str(res.error), secret, limit=200) if res.error else None)
            if res.error is None or not res.error.transient or attempt == max_attempts:
                break
            delay = res.error.retry_after if res.error.retry_after is not None else \
                self.settings.ai_retry_base_delay_seconds * (2 ** (attempt - 1))
            self.sleep(min(30.0, max(0.0, delay)))
        res.latency_ms = int((time.monotonic() - t0) * 1000)
        res.completed_at = self.clock()
        return res

    def _record_call(self, job_id, p: PreparedAnalysis, provider: AIProvider, attempt: int, status: str,
                     duration: int, r: AIResponse | None, started: datetime) -> None:
        try:
            with self.session_factory() as s:
                s.add(AIProviderCall(job_id=job_id, stage3b_extraction_id=p.stage3b_extraction_id,
                                     provider=provider.name[:40], model=provider.model[:120], attempt=attempt,
                                     status=status[:40], duration_ms=duration,
                                     input_tokens=r.input_tokens if r else None,
                                     output_tokens=r.output_tokens if r else None, started_at=started))
                s.commit()
        except Exception:  # accounting must never break an analysis
            logger.exception("ai_provider_call_record_failed")

    # ------------------------------------------------------------------
    def interpret(self, p: PreparedAnalysis, response: AIResponse) -> Interpretation:
        """Raises ResponseInvalid for malformed / schema-invalid / empty responses."""
        envelope = parse_envelope(response.text)
        grounded = ground(envelope, p.chunks.sent)
        excluded = [c.key for c in p.chunks.chunks if not c.sent and c.exclusion_reason in ("CHUNK_LIMIT",
                                                                                             "CHAR_LIMIT")]
        flags = build_flags(grounded, p.stage3b, truncated=p.chunks.truncated, excluded_keys=excluded)
        rejected_req = any(r.get("kind") in ("requirement", "summary") for r in grounded.rejected)
        high = any(f.severity == Severity.HIGH.value for f in flags)
        if rejected_req:
            status, code = RunStatus.PARTIAL_SUCCESS.value, AIErrorCode.EVIDENCE_REJECTED.value
        elif p.chunks.truncated:
            status, code = RunStatus.PARTIAL_SUCCESS.value, AIErrorCode.INPUT_TRUNCATED.value
        elif high:
            status, code = RunStatus.PARTIAL_SUCCESS.value, AIErrorCode.REVIEW_FLAGS.value
        else:
            status, code = RunStatus.SUCCESS.value, None
        result = Interpretation(grounded, flags, status, code)
        if p.corpus:
            from app.corpus.analysis import corpus_flags
            return corpus_flags(p, result)
        return result

    # ------------------------------------------------------------------
    def persist(self, session: Session, p: PreparedAnalysis, call: CallResult, it: Interpretation) -> int:
        """Add run + chunks + requirements + evidence + flags to the caller's transaction (no commit)."""
        src, now, resp = p.source, self.clock(), call.response
        if p.corpus:
            from app.corpus.service import build_corpus
            from app.corpus.analysis import CORPUS_PROMPT_VERSION
            if build_corpus(session, p.corpus['tender_id'])['fingerprint'] != p.corpus['fingerprint']:
                raise ValueError('Corpus changed during provider call; result not persisted')
            if p.force:
                session.execute(update(AIAnalysisRun).where(AIAnalysisRun.analysis_scope=='TENDER_CORPUS',
                    AIAnalysisRun.tender_id==src.tender_id, AIAnalysisRun.corpus_fingerprint==p.corpus['fingerprint'],
                    AIAnalysisRun.provider==p.provider, AIAnalysisRun.model==p.model,
                    AIAnalysisRun.prompt_version==CORPUS_PROMPT_VERSION, AIAnalysisRun.schema_version==SCHEMA_VERSION)
                    .values(is_current=False))
        if p.force and not p.corpus:
            session.execute(update(AIAnalysisRun)
                            .where(AIAnalysisRun.analysis_scope == 'DOCUMENT', AIAnalysisRun.stage3b_extraction_id == p.stage3b_extraction_id,
                                   AIAnalysisRun.provider == p.provider, AIAnalysisRun.model == p.model,
                                   AIAnalysisRun.prompt_version == PROMPT_VERSION,
                                   AIAnalysisRun.schema_version == SCHEMA_VERSION,
                                   AIAnalysisRun.is_current.is_(True))
                            .values(is_current=False, updated_at=now).execution_options(synchronize_session=False))
        g = it.grounded
        run = AIAnalysisRun(
            stage3b_extraction_id=p.stage3b_extraction_id, stage3a_extraction_id=src.stage3a_extraction_id,
            document_version_id=src.document_version_id, document_id=src.document_id, tender_id=src.tender_id,
            bid_number=src.bid_number, document_type=src.document_type, version_number=src.version_number,
            analyzer_name=ANALYZER_NAME, provider=p.provider, model=p.model, prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION, chunker_version=CHUNKER_VERSION, status=it.status,
            status_code=it.status_code, is_current=True, summary=g.summary,
            chunks_total=len(p.chunks.chunks), chunks_sent=len(p.chunks.sent),
            input_characters=p.prompt.characters, requirements_count=len(g.requirements),
            rejected_count=len(g.rejected), flags_count=len(it.flags),
            ambiguities_count=len(g.ambiguities) + sum(1 for r in g.requirements if r.ambiguity),
            conflicts_count=sum(1 for f in it.flags if f.flag_type in (FlagType.AI_DETERMINISTIC_CONFLICT.value,
                                                                       FlagType.CONTRADICTORY_REQUIREMENT.value)),
            input_tokens=resp.input_tokens, output_tokens=resp.output_tokens, total_tokens=resp.total_tokens,
            finish_reason=(resp.finish_reason or None) and str(resp.finish_reason)[:40],
            provider_attempts=call.attempts, latency_ms=call.latency_ms, request_sha256=p.prompt.sha256,
            response_sha256=hashlib.sha256(resp.text.encode("utf-8")).hexdigest(),
            rejected_json=json.dumps(g.rejected, ensure_ascii=False) if g.rejected else None,
            started_at=call.started_at, completed_at=call.completed_at, created_at=now, updated_at=now)
        if p.corpus:
            from app.corpus.analysis import CORPUS_PROMPT_VERSION, persist_sources
            run.analysis_scope='TENDER_CORPUS'
            run.corpus_fingerprint=p.corpus['fingerprint']
            run.corpus_completeness=p.corpus['completeness']
            run.corpus_snapshot_json=json.dumps({**p.corpus, "ai_input_coverage": p.input_coverage},ensure_ascii=False,sort_keys=True)
            run.prompt_version=CORPUS_PROMPT_VERSION
            run.conflicts_count += sum(f.flag_type=='CROSS_DOCUMENT_CONFLICT' for f in it.flags)
        session.add(run)
        session.flush()
        if p.corpus:
            persist_sources(session,run,p)
        chunk_rows = {}
        for c in p.chunks.chunks:
            chunk_src = p.chunk_sources.get(c.key, src)
            row = AIEvidenceChunk(
                analysis_run_id=run.id, chunk_key=c.key, sequence=c.sequence, kind=c.kind, source_type=c.source_type,
                stage3a_extraction_id=chunk_src.stage3a_extraction_id, document_version_id=chunk_src.document_version_id,
                page_number=c.page_number, page_end=c.page_end, section_id=c.section_id,
                section_heading=c.section_heading, table_id=c.table_id, text=c.text, char_count=c.char_count,
                text_sha256=c.sha256, sent=c.sent, exclusion_reason=c.exclusion_reason, created_at=now)
            session.add(row)
            chunk_rows[c.key] = row
        session.flush()
        req_rows = {}
        for r in g.requirements:
            row = AIRequirement(
                analysis_run_id=run.id, tender_id=src.tender_id, sequence=r.sequence,
                requirement_type=r.requirement_type, model_requirement_type=r.model_requirement_type,
                category=r.category, title=r.title, summary=r.summary, obligation=r.obligation,
                obligation_level=r.obligation_level, model_obligation_level=r.model_obligation_level,
                level_adjustment=r.level_adjustment, condition_text=r.condition, value_text=r.value_text,
                value_number=r.value_number, unit=(r.unit or None) and r.unit[:32], applies_to=r.applies_to,
                risk_flags_json=json.dumps(r.risk_flags) if r.risk_flags else None, ambiguity=r.ambiguity,
                is_buyer_atc=r.is_buyer_atc, created_at=now)
            session.add(row)
            req_rows[r.sequence] = (row, r)
        session.flush()
        for row, r in req_rows.values():
            for ev in r.evidence:
                c = ev.chunk
                session.add(AIRequirementEvidence(
                    requirement_id=row.id, analysis_run_id=run.id, chunk_id=chunk_rows[c.key].id, chunk_key=c.key,
                    page_number=c.page_number, section_id=c.section_id, section_heading=c.section_heading,
                    quote=ev.quote[:2000], created_at=now))
        for f in it.flags:
            session.add(AIAnalysisFlag(
                analysis_run_id=run.id,
                requirement_id=req_rows[f.requirement_seq][0].id if f.requirement_seq in req_rows else None,
                flag_type=f.flag_type, severity=f.severity, message=f.message[:4000],
                stage3b_field_name=f.stage3b_field_name, stage3b_value=f.stage3b_value,
                stage3b_evidence_strength=f.stage3b_evidence_strength, ai_value=f.ai_value,
                chunk_keys_json=json.dumps(f.chunk_keys) if f.chunk_keys else None, created_at=now))
        session.flush()
        log_event(logger, logging.INFO if it.status == RunStatus.SUCCESS.value else logging.WARNING,
                  "ai_analysis_completed", analysis_run_id=run.id, stage3b_extraction_id=p.stage3b_extraction_id,
                  bid=src.bid_number, provider=p.provider, model=p.model, status=it.status,
                  requirements=len(g.requirements), rejected=len(g.rejected), flags=len(it.flags),
                  chunks_sent=len(p.chunks.sent), latency_ms=call.latency_ms, input_tokens=resp.input_tokens,
                  output_tokens=resp.output_tokens)
        return run.id

    # ------------------------------------------------------------------
    def analyze(self, stage3b_extraction_id: int, force: bool = False) -> AnalysisOutcome:
        """prepare -> call -> interpret -> persist + commit (CLI/tests; the worker finishes its job atomically)."""
        p = self.prepare(stage3b_extraction_id, force)
        if p.not_ready_code:
            return AnalysisOutcome(NOT_READY, stage3b_extraction_id, error_code=p.not_ready_code,
                                   error_message=p.not_ready_message)
        if p.already_id is not None:
            return AnalysisOutcome(ALREADY, stage3b_extraction_id, p.already_id)
        call = self.call(p)
        if call.error is not None:
            e = call.error
            return AnalysisOutcome(PROVIDER_FAILED, stage3b_extraction_id, error_code=e.code,
                                   error_message=self.safe_message(e), transient=e.transient, blocking=e.blocking)
        try:
            it = self.interpret(p, call.response)
        except ResponseInvalid as exc:
            return AnalysisOutcome(RESPONSE_INVALID, stage3b_extraction_id, error_code=exc.code,
                                   error_message=str(exc)[:500])
        with self.session_factory() as s:
            try:
                run_id = self.persist(s, p, call, it)
                s.commit()
            except IntegrityError:
                s.rollback()
                return AnalysisOutcome(ALREADY, stage3b_extraction_id,
                                       current_analysis_id(s, stage3b_extraction_id, p.provider, p.model))
            except OperationalError as exc:
                s.rollback()
                return AnalysisOutcome(ERROR, stage3b_extraction_id, error_code=AIErrorCode.DATABASE_ERROR.value,
                                       error_message=str(exc)[:300], transient=True)
        return AnalysisOutcome(ANALYZED, stage3b_extraction_id, run_id, it.status, it.status_code,
                               requirements=len(it.grounded.requirements), flags=len(it.flags))

    def safe_message(self, exc: BaseException) -> str:
        secret = self.settings.ai_api_key_value()
        return redact(str(exc), secret, limit=500)
