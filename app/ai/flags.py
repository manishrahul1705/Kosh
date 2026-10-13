"""Deterministic disagreement / review flagging (no AI involved here).

Stage 3B stays authoritative: its values are NEVER modified. When an AI
interpretation disagrees with a Stage 3B fact, a flag is recorded with both
sides and the evidence so a human can review it.

* AI_DETERMINISTIC_CONFLICT  HIGH     AI reads a MANDATORY requirement where Stage 3B resolved the
                                      corresponding boolean to FALSE (e.g. EMD required vs. EMD table "No")
                             WARNING  AI value (duration / percent) differs from the Stage 3B value
* AI_SUPPLEMENTS_UNKNOWN     INFO     Stage 3B UNKNOWN, AI found grounded text about it
* CONTRADICTORY_REQUIREMENT  WARNING  two mandatory AI requirements of one type with different values
* AMBIGUOUS_ATC              WARNING  ambiguity reported on buyer-added ATC text
* REVIEW_REQUIRED            INFO     other ambiguity, or obligation level downgraded by the guards
* RESTRICTIVE_CLAUSE         WARNING  restrictive / unusual risk flags
* EVIDENCE_REJECTED          WARNING  model items rejected by grounding validation
* INPUT_TRUNCATED            WARNING  relevant chunks not sent because of the configured limits
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.constants import (
    RESTRICTIVE_RISKS,
    STAGE3B_BOOL_FIELD_BY_TYPE,
    STAGE3B_VALUE_FIELD_BY_TYPE,
    FlagType,
    Severity,
)
from app.ai.grounding import GroundedOutput, ValidRequirement
from app.fields.normalizers import Normalized, norm_duration, norm_percent

_DAYS = {"DAYS": 1.0, "WEEKS": 7.0, "MONTHS": 30.0, "YEARS": 365.0}


@dataclass
class Stage3BValue:
    field_name: str
    status: str
    tri_state: str | None
    value_text: str | None
    value_number: float | None
    unit: str | None
    strength: str | None


@dataclass
class FlagDraft:
    flag_type: str
    severity: str
    message: str
    requirement_seq: int | None = None
    stage3b_field_name: str | None = None
    stage3b_value: str | None = None
    stage3b_evidence_strength: str | None = None
    ai_value: str | None = None
    chunk_keys: list[str] | None = None


def _ai_quantity(req: ValidRequirement, kind: str) -> float | None:
    """AI value in comparable units: days for durations, number for percent."""
    if req.value_number is None:
        return None
    raw = f"{req.value_text or req.value_number} {req.unit or ''}".strip()
    if kind == "PERCENT":
        r = norm_percent(raw)
        return float(r.number) if isinstance(r, Normalized) and r.number is not None else req.value_number
    r = norm_duration(raw)
    if isinstance(r, Normalized) and r.unit in _DAYS and r.number is not None:
        return r.number * _DAYS[r.unit]
    return None


def _stage3b_quantity(v: Stage3BValue, kind: str) -> float | None:
    if v.status != "RESOLVED" or v.value_number is None:
        return None
    if kind == "PERCENT":
        return v.value_number
    return v.value_number * _DAYS[v.unit] if v.unit in _DAYS else None


def build_flags(out: GroundedOutput, stage3b: dict[str, Stage3BValue], *, truncated: bool,
                excluded_keys: list[str]) -> list[FlagDraft]:
    flags: list[FlagDraft] = []
    for r in out.requirements:
        keys = r.chunk_keys
        # --- Stage 3B boolean disagreement ---------------------------------------------
        bool_field = STAGE3B_BOOL_FIELD_BY_TYPE.get(r.requirement_type)
        b = stage3b.get(bool_field) if bool_field else None
        if b is not None and r.obligation_level == "MANDATORY":
            if b.status == "RESOLVED" and b.tri_state == "FALSE":
                flags.append(FlagDraft(
                    FlagType.AI_DETERMINISTIC_CONFLICT.value, Severity.HIGH.value,
                    f"AI reads a mandatory {r.requirement_type} requirement, but Stage 3B resolved "
                    f"{bool_field} = FALSE ({b.strength}). Stage 3B value kept; review the cited text.",
                    r.sequence, bool_field, "FALSE", b.strength, r.obligation_level, keys))
            elif b.status == "UNKNOWN":
                flags.append(FlagDraft(
                    FlagType.AI_SUPPLEMENTS_UNKNOWN.value, Severity.INFO.value,
                    f"Stage 3B found no deterministic value for {bool_field}; AI cites text stating a "
                    f"{r.requirement_type} requirement.", r.sequence, bool_field, None, None, r.obligation_level,
                    keys))
        # --- Stage 3B value disagreement -------------------------------------------------
        spec = STAGE3B_VALUE_FIELD_BY_TYPE.get(r.requirement_type)
        if spec and r.value_number is not None:
            fname, kind = spec
            v = stage3b.get(fname)
            if v is not None:
                ai_q, b_q = _ai_quantity(r, kind), _stage3b_quantity(v, kind)
                if ai_q is not None and b_q is not None and abs(ai_q - b_q) > 1e-6:
                    flags.append(FlagDraft(
                        FlagType.AI_DETERMINISTIC_CONFLICT.value, Severity.WARNING.value,
                        f"AI value for {r.requirement_type} ({r.value_text} {r.unit or ''}".rstrip()
                        + f") differs from Stage 3B {fname} ({v.value_text}). Stage 3B value kept.",
                        r.sequence, fname, v.value_text, v.strength, f"{r.value_text} {r.unit or ''}".strip(), keys))
                elif ai_q is not None and v.status == "UNKNOWN":
                    flags.append(FlagDraft(
                        FlagType.AI_SUPPLEMENTS_UNKNOWN.value, Severity.INFO.value,
                        f"Stage 3B found no deterministic {fname}; AI cites text stating "
                        f"{r.value_text} {r.unit or ''}".rstrip() + ".", r.sequence, fname, None, None,
                        f"{r.value_text} {r.unit or ''}".strip(), keys))
        # --- ambiguity / review --------------------------------------------------------
        if r.ambiguity:
            ftype = FlagType.AMBIGUOUS_ATC if r.is_buyer_atc else FlagType.REVIEW_REQUIRED
            sev = Severity.WARNING if r.is_buyer_atc else Severity.INFO
            flags.append(FlagDraft(ftype.value, sev.value, f"{r.title}: {r.ambiguity}"[:2000], r.sequence,
                                   chunk_keys=keys))
        if r.level_adjustment in ("NO_OBLIGATION_WORDING", "NO_CONDITION_STATED", "UNRECOGNIZED_LEVEL"):
            flags.append(FlagDraft(
                FlagType.REVIEW_REQUIRED.value, Severity.INFO.value,
                f"{r.title}: model level '{r.model_obligation_level}' changed to {r.obligation_level} "
                f"({r.level_adjustment}).", r.sequence, chunk_keys=keys))
        risky = [f for f in r.risk_flags if f in RESTRICTIVE_RISKS]
        if risky:
            flags.append(FlagDraft(FlagType.RESTRICTIVE_CLAUSE.value, Severity.WARNING.value,
                                   f"{r.title}: {', '.join(risky)}", r.sequence, chunk_keys=keys))
    # --- contradictions between AI requirements -------------------------------------------
    seen: dict[tuple[str, str], ValidRequirement] = {}
    for r in out.requirements:
        if r.obligation_level != "MANDATORY" or r.value_number is None:
            continue
        spec = STAGE3B_VALUE_FIELD_BY_TYPE.get(r.requirement_type)
        kind = spec[1] if spec else "RAW"
        q = _ai_quantity(r, kind) if spec else r.value_number
        if q is None:
            continue
        unit_key = kind if spec else (r.unit or "").upper()
        k = (r.requirement_type, unit_key)
        prev = seen.get(k)
        if prev is None:
            seen[k] = r
            continue
        pq = _ai_quantity(prev, kind) if spec else prev.value_number
        if pq is not None and abs(pq - q) > 1e-6:
            flags.append(FlagDraft(
                FlagType.CONTRADICTORY_REQUIREMENT.value, Severity.WARNING.value,
                f"Two mandatory {r.requirement_type} requirements state different values: "
                f"'{prev.value_text} {prev.unit or ''}'".rstrip() + f" vs '{r.value_text} {r.unit or ''}'".rstrip(),
                r.sequence, ai_value=f"{r.value_text} {r.unit or ''}".strip(),
                chunk_keys=sorted(set(prev.chunk_keys) | set(r.chunk_keys))))
    for a in out.ambiguities:
        ftype = FlagType.AMBIGUOUS_ATC if a.is_buyer_atc else FlagType.REVIEW_REQUIRED
        sev = Severity.WARNING if a.is_buyer_atc else Severity.INFO
        flags.append(FlagDraft(ftype.value, sev.value, a.description[:2000],
                               chunk_keys=sorted({e.chunk.key for e in a.evidence})))
    for rej in out.rejected:
        if rej.get("kind") in ("requirement", "summary"):
            flags.append(FlagDraft(FlagType.EVIDENCE_REJECTED.value, Severity.WARNING.value,
                                   f"Model {rej.get('kind')} rejected: {rej.get('reason')}"
                                   + (f" ({rej.get('title')})" if rej.get("title") else "")))
    if truncated:
        flags.append(FlagDraft(FlagType.INPUT_TRUNCATED.value, Severity.WARNING.value,
                               "Not all relevant evidence chunks were sent (AI_MAX_CHUNKS_PER_ANALYSIS / "
                               "AI_MAX_INPUT_CHARACTERS). Requirements in excluded chunks are not covered.",
                               chunk_keys=excluded_keys))
    return flags
