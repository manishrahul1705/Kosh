"""Grounding / anti-hallucination validation of model output.

Nothing the model returns is trusted as-is:
* each item is validated individually against the strict schema;
* every evidence reference must name a chunk that was ACTUALLY SENT in this run,
  and its quote must be found in that chunk's text (whitespace/case-insensitive;
  "..." may join verbatim fragments). Unknown chunk id -> the requirement is
  rejected; no verified evidence left -> rejected;
* MANDATORY needs obligation wording ("shall", "must", "required", ...) in or
  around the quoted text, CONDITIONAL needs a stated condition - otherwise the
  level is downgraded to UNKNOWN (the model's label is kept for audit);
* seller-eligibility verdicts ("you are eligible", "bidder is not eligible", PASS/FAIL)
  are rejected - Stage 3C interprets requirements only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.ai.chunker import Chunk
from app.ai.constants import CATEGORY_BY_TYPE, ChunkKind
from app.ai.schema import (
    MAX_AMBIGUITIES,
    MAX_REQUIREMENTS,
    Envelope,
    map_applies_to,
    map_level,
    map_requirement_type,
    map_risks,
    short_errors,
    validate_ambiguity,
    validate_requirement,
)

OBLIGATION_WORDS = re.compile(
    r"\b(shall|must|required|requires|require|mandatory|compulsory|has to|have to|need to|needs to|"
    r"is to be|are to be|to be (?:submitted|uploaded|provided|furnished|delivered|attached)|should|"
    r"obligatory|necessary|bound to|will have to)\b", re.I)
CONDITION_WORDS = re.compile(r"\b(if|in case|where|whereas|subject to|unless|provided that|only when|"
                             r"in the event|wherever|as applicable|if any)\b", re.I)
# Second-person or bidder-specific eligibility verdicts (Stage 4 territory).
_VERDICT = re.compile(
    r"\b(you|your (?:company|firm|business))\s+(?:are|is|would be|will be|do not|don't|does not|may not)\s+"
    r"(?:not\s+)?(?:be\s+)?(eligible|ineligible|qualif\w*|disqualif\w*)\b"
    r"|\b(?:the\s+)?(?:seller|bidder)\s+(?:is|are)\s+(?:not\s+)?(?:eligible|ineligible)\s*(?:[.!]|$)"
    r"|\beligibility\s*(?:result|verdict|status)\s*[:=]\s*(?:pass|fail|eligible|not eligible)\b"
    r"|^\s*(?:pass|fail|eligible|not eligible|ineligible)\s*[.!]?\s*$", re.I)


def norm(text: str) -> str:
    t = text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(t.split())


MIN_QUOTE_CHARS = 20      # joined verbatim text a quote must contain ...
MIN_QUOTE_WORDS = 4       # ... and words - unless it covers most of a very short chunk
MIN_FRAGMENT_CHARS = 10   # each "..."-separated fragment
MAX_FRAGMENTS = 4


def quote_in_chunk(quote: str, chunk_text: str) -> int | None:
    """Position of the (normalized) quote in the (normalized) chunk text, or None.

    A quote must be substantial: >= MIN_QUOTE_CHARS characters and >= MIN_QUOTE_WORDS
    words in total, or cover >= 40 % of a tiny chunk (<= 120 chars) (e.g. "EMD Detail / Required: No").
    "..." / "…" may join up to MAX_FRAGMENTS verbatim fragments (each >= MIN_FRAGMENT_CHARS),
    which must appear in order. A tiny quote such as "the" never grounds anything.
    """
    hay = norm(chunk_text)
    frags = [norm(f).strip(" .,;:\"'") for f in re.split(r"\.\.\.+|…", quote)]
    frags = [f for f in frags if f]
    if not frags or len(frags) > MAX_FRAGMENTS:
        return None
    if len(frags) > 1 and any(len(f) < MIN_FRAGMENT_CHARS for f in frags):
        return None
    total = sum(len(f) for f in frags)
    words = sum(len(f.split()) for f in frags)
    tiny_chunk_cover = len(hay) <= 120 and total >= 6 and total >= 0.4 * len(hay)
    if not ((total >= MIN_QUOTE_CHARS and words >= MIN_QUOTE_WORDS) or tiny_chunk_cover):
        return None
    pos = start = None
    for f in frags:
        i = hay.find(f, 0 if pos is None else pos)
        if i < 0:
            return None
        start = i if start is None else start
        pos = i + len(f)
    return start


def _sentence_window(text: str, at: int, length: int) -> str:
    """The sentence(s) of normalized ``text`` containing [at, at+length), capped to +-300 chars."""
    lo = max(text.rfind(". ", 0, at), text.rfind("; ", 0, at), -1) + 1
    hi_dot = text.find(". ", at + length)
    hi = len(text) if hi_dot < 0 else hi_dot + 1
    return text[max(lo, at - 300):min(hi, at + length + 300)]


def _context(chunk: Chunk, quote: str) -> str:
    """Wording around a quote, used by the obligation-level guards.

    TABLE chunks are line-based ("Label: value"): only the lines the quote touches count.
    Prose chunks: the surrounding sentence(s).
    """
    if chunk.source_type == "TABLE":
        q = norm(quote)
        lines = [norm(ln) for ln in chunk.text.splitlines()]
        hit = [ln for ln in lines if ln and (ln in q or q in ln or any(f and f in ln for f in q.split("...")))]
        return " ".join(hit) if hit else q
    t = norm(chunk.text)
    at = quote_in_chunk(quote, chunk.text) or 0
    return _sentence_window(t, at, len(norm(quote)))


@dataclass
class VerifiedEvidence:
    chunk: Chunk
    quote: str


@dataclass
class ValidRequirement:
    sequence: int
    requirement_type: str
    model_requirement_type: str | None
    category: str
    title: str
    summary: str | None
    obligation: str | None
    obligation_level: str
    model_obligation_level: str | None
    level_adjustment: str | None
    condition: str | None
    value_text: str | None
    value_number: float | None
    unit: str | None
    applies_to: str
    risk_flags: list[str]
    ambiguity: str | None
    evidence: list[VerifiedEvidence]

    @property
    def is_buyer_atc(self) -> bool:
        return any(e.chunk.kind == ChunkKind.BUYER_ATC.value for e in self.evidence)

    @property
    def chunk_keys(self) -> list[str]:
        return sorted({e.chunk.key for e in self.evidence}, key=lambda k: int(k[1:]) if k[1:].isdigit() else 0)


@dataclass
class ValidAmbiguity:
    description: str
    evidence: list[VerifiedEvidence]

    @property
    def is_buyer_atc(self) -> bool:
        return any(e.chunk.kind == ChunkKind.BUYER_ATC.value for e in self.evidence)


@dataclass
class GroundedOutput:
    summary: str
    requirements: list[ValidRequirement] = field(default_factory=list)
    ambiguities: list[ValidAmbiguity] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        m = _NUM.search(value.replace(",", ""))
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
    return None


def _check_evidence(refs, sent: dict[str, Chunk]) -> tuple[list[VerifiedEvidence], str | None]:
    """-> (verified evidence, rejection reason or None)."""
    verified: list[VerifiedEvidence] = []
    for ref in refs:
        chunk = sent.get(ref.chunk_id.strip().upper())
        if chunk is None:
            return [], f"UNKNOWN_EVIDENCE_ID:{ref.chunk_id[:16]}"
        if quote_in_chunk(ref.quote, chunk.text) is None:
            continue
        verified.append(VerifiedEvidence(chunk, ref.quote))
    if not verified:
        return [], "QUOTE_NOT_IN_EVIDENCE"
    return verified, None


def _texts(item) -> list[str]:
    vals = (item.title, item.summary, item.obligation, item.condition, item.ambiguity,
            item.value if isinstance(item.value, str) else None)
    return [x for x in vals if x]


def ground(envelope: Envelope, sent_chunks: list[Chunk]) -> GroundedOutput:
    sent = {c.key.upper(): c for c in sent_chunks}
    out = GroundedOutput(summary=envelope.summary.strip())
    if _VERDICT.search(out.summary):
        out.rejected.append({"kind": "summary", "reason": "SELLER_ELIGIBILITY_VERDICT"})
        out.summary = "[summary withheld: it contained a seller-eligibility statement]"

    for idx, raw in enumerate(envelope.requirements):
        if len(out.requirements) >= MAX_REQUIREMENTS:
            out.rejected.append({"kind": "requirement", "index": idx, "reason": "LIMIT_EXCEEDED"})
            continue
        try:
            item = validate_requirement(raw)
        except ValidationError as exc:
            out.rejected.append({"kind": "requirement", "index": idx, "reason": "SCHEMA_INVALID",
                                 "detail": short_errors(exc)})
            continue
        if any(_VERDICT.search(t) for t in _texts(item)):
            out.rejected.append({"kind": "requirement", "index": idx, "title": item.title[:120],
                                 "reason": "SELLER_ELIGIBILITY_VERDICT"})
            continue
        evidence, why = _check_evidence(item.evidence, sent)
        if why:
            out.rejected.append({"kind": "requirement", "index": idx, "title": item.title[:120], "reason": why,
                                 "chunk_ids": [e.chunk_id[:16] for e in item.evidence]})
            continue
        rtype, raw_type = map_requirement_type(item.requirement_type)
        level = map_level(item.obligation_level)
        model_level = item.obligation_level[:32]
        adjustment = None if level == model_level.strip().upper() else "UNRECOGNIZED_LEVEL"
        context = " ".join(_context(ev.chunk, ev.quote) for ev in evidence)
        if level == "MANDATORY" and not OBLIGATION_WORDS.search(context):
            level, adjustment = "UNKNOWN", "NO_OBLIGATION_WORDING"
        elif level == "CONDITIONAL" and not (item.condition and item.condition.strip()) \
                and not CONDITION_WORDS.search(context):
            level, adjustment = "UNKNOWN", "NO_CONDITION_STATED"
        value_text = None if item.value is None else str(item.value)[:500]
        value_number, unit = _number(item.value), (item.unit or None)
        ambiguity = item.ambiguity or None
        if rtype == "TURNOVER":
            from app.fields.turnover import turnover_amount
            # Quotes have already been verified against the chunks actually sent.
            amount = turnover_amount("\n".join(ev.quote for ev in evidence))
            value_number = amount.number if amount else None
            unit = amount.unit if amount else None
            value_text = amount.text if amount else value_text
            if amount is None:
                ambiguity = "Turnover amount or unit cannot be normalized from verified evidence."
        if any(ev.chunk.review_required for ev in evidence):
            value_number,unit,level=None,None,"UNKNOWN"
            adjustment="LOW_OCR_CONFIDENCE"
            ambiguity="OCR evidence has low or unknown confidence; human verification is required."
        out.requirements.append(ValidRequirement(
            sequence=len(out.requirements) + 1, requirement_type=rtype, model_requirement_type=raw_type,
            category=CATEGORY_BY_TYPE.get(rtype, "OTHER"), title=item.title[:255], summary=item.summary,
            obligation=item.obligation, obligation_level=level, model_obligation_level=model_level,
            level_adjustment=adjustment, condition=(item.condition or None), value_text=value_text,
            value_number=value_number, unit=unit, applies_to=map_applies_to(item.applies_to),
            risk_flags=map_risks(item.risk_flags), ambiguity=ambiguity, evidence=evidence))

    for idx, raw in enumerate(envelope.ambiguities):
        if len(out.ambiguities) >= MAX_AMBIGUITIES:
            out.rejected.append({"kind": "ambiguity", "index": idx, "reason": "LIMIT_EXCEEDED"})
            continue
        try:
            item = validate_ambiguity(raw)
        except ValidationError as exc:
            out.rejected.append({"kind": "ambiguity", "index": idx, "reason": "SCHEMA_INVALID",
                                 "detail": short_errors(exc)})
            continue
        if _VERDICT.search(item.description):
            out.rejected.append({"kind": "ambiguity", "index": idx, "reason": "SELLER_ELIGIBILITY_VERDICT"})
            continue
        evidence, why = _check_evidence(item.evidence, sent)
        if why:
            out.rejected.append({"kind": "ambiguity", "index": idx, "reason": why})
            continue
        out.ambiguities.append(ValidAmbiguity(item.description, evidence))
    return out
