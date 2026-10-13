"""Deterministic conflict handling: every candidate is kept; none is silently dropped.

Scalar fields:
  1. Non-informative candidates (masked "*****", "N/a", unparseable) -> IGNORED.
     If nothing informative remains: UNKNOWN (reason: MASKED / NOT_APPLICABLE /
     UNPARSEABLE / NOT_FOUND - in that order of precedence).
  2. Rank candidates by strength (SYSTEM_METADATA < EXACT_TABLE < SECTION_TABLE <
     EXACT_LABEL < SECTION_CONTEXT = DERIVED < REGEX_FALLBACK).
  3. Two different values at the strongest rank -> CONFLICT.
  4. One value at the strongest rank:
       * every other candidate agrees                      -> RESOLVED (AGREES)
       * disagreeing candidates are ONLY page-text parsing
         tiers (EXACT_LABEL / REGEX_FALLBACK) and the field
         is not ``strict``                                  -> RESOLVED; they are kept as OVERRIDDEN
       * any other disagreeing candidate (another table,
         an ATC clause, a derived fact) or a strict field   -> CONFLICT (all kept, none selected)
LIST fields (``merge``): items of all candidates are unioned (RESOLVED).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.fields.constants import (
    OVERRIDABLE,
    STRENGTH_RANK,
    Disposition,
    FieldStatus,
    Reason,
    TriState,
    ValueType,
)
from app.fields.evidence import Candidate
from app.fields.normalizers import Normalized, Rejected
from app.fields.registry import FieldSpec

_REASON_ORDER = (Reason.MASKED_IN_SOURCE.value, Reason.NOT_APPLICABLE_IN_SOURCE.value,
                 Reason.UNPARSEABLE.value, Reason.NOT_FOUND.value)


@dataclass
class FieldResult:
    spec: FieldSpec
    status: str
    reason: str | None = None
    selected: Normalized | None = None
    strength: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    dispositions: list[str] = field(default_factory=list)

    @property
    def tri_state(self) -> str | None:
        if self.spec.value_type != ValueType.BOOL.value:
            return None
        if self.status == FieldStatus.RESOLVED.value and self.selected is not None:
            return self.selected.tri_state
        return TriState.UNKNOWN.value

    def value_json(self) -> str | None:
        if self.status == FieldStatus.RESOLVED.value and self.selected is not None:
            payload = {"value": self.selected.value}
            if self.selected.details:
                payload["details"] = self.selected.details
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if self.status == FieldStatus.CONFLICT.value:
            vals = []
            for c, d in zip(self.candidates, self.dispositions):
                if d == Disposition.CONFLICTING.value and isinstance(c.result, Normalized):
                    vals.append({"value": c.result.value, "strength": c.strength, "page": c.page_number,
                                 "rule": c.rule})
            return json.dumps({"conflicting_values": vals}, ensure_ascii=False, sort_keys=True)
        return None


def item_text(item) -> str:
    """Readable text of one list item (plain string, ATC clause or consignee record)."""
    if isinstance(item, str):
        return item
    if "title" in item:
        return str(item["title"])
    if "sno" in item:
        parts = [f"#{item['sno']}", item.get("address") or item.get("consignee") or "(masked)"]
        if item.get("quantity") is not None:
            parts.append(f"qty={item['quantity']}")
        if item.get("delivery_days") is not None:
            parts.append(f"days={item['delivery_days']}")
        return " ".join(str(p) for p in parts)
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def _rank(c: Candidate) -> int:
    return STRENGTH_RANK.get(c.strength, 9)


def resolve(spec: FieldSpec, cands: list[Candidate]) -> FieldResult:
    cands = sorted(cands, key=_rank)  # stable: equal ranks keep document order
    res = FieldResult(spec, FieldStatus.UNKNOWN.value, candidates=cands,
                      dispositions=[Disposition.IGNORED.value] * len(cands))
    info = [i for i, c in enumerate(cands) if isinstance(c.result, Normalized)]
    if not info:
        reasons = {c.result.reason for c in cands if isinstance(c.result, Rejected)}
        res.reason = next((r for r in _REASON_ORDER if r in reasons), Reason.NOT_FOUND.value)
        return res

    if spec.merge:
        items, seen = [], set()
        for i in info:
            for item in cands[i].result.value:
                k = json.dumps(item, sort_keys=True, ensure_ascii=False).casefold()
                if k not in seen:
                    seen.add(k)
                    items.append(item)
            res.dispositions[i] = Disposition.AGREES.value
        first = cands[info[0]]
        res.dispositions[info[0]] = Disposition.SELECTED.value
        texts = [item_text(i) for i in items]
        res.selected = Normalized(items, "l:" + "|".join(sorted(t.casefold() for t in texts))[:250],
                                  " | ".join(str(t) for t in texts), details=first.result.details)
        res.status, res.strength = FieldStatus.RESOLVED.value, first.strength
        return res

    top_rank = _rank(cands[info[0]])
    top_keys = {cands[i].result.key for i in info if _rank(cands[i]) == top_rank}
    if len(top_keys) > 1:
        for i in info:
            res.dispositions[i] = Disposition.CONFLICTING.value
        res.status, res.reason = FieldStatus.CONFLICT.value, Reason.CONFLICTING_EVIDENCE.value
        return res
    key = top_keys.pop()
    disagree = [i for i in info if cands[i].result.key != key]
    if disagree and (spec.strict or any(cands[i].strength not in OVERRIDABLE for i in disagree)):
        for i in info:
            res.dispositions[i] = Disposition.CONFLICTING.value
        res.status, res.reason = FieldStatus.CONFLICT.value, Reason.CONFLICTING_EVIDENCE.value
        return res
    sel = info[0]
    for i in info:
        res.dispositions[i] = (Disposition.SELECTED.value if i == sel else
                               Disposition.OVERRIDDEN.value if i in disagree else Disposition.AGREES.value)
    res.selected, res.strength = cands[sel].result, cands[sel].strength
    res.status = FieldStatus.RESOLVED.value
    return res
