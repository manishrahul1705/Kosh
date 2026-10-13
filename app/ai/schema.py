"""Stage 3C structured output contract (SCHEMA_VERSION = stage3c-schema-v1).

The model must return ONE JSON object:

    {
      "summary": "<concise neutral tender summary>",
      "requirements": [
        {
          "requirement_type": "<taxonomy value>",
          "title": "...", "summary": "...", "obligation": "<what must be done>",
          "obligation_level": "MANDATORY|OPTIONAL|CONDITIONAL|INFORMATIONAL|UNKNOWN",
          "mandatory": true|false|null,            # optional, informational only
          "condition": "<when it applies>"|null,
          "value": <string|number|null>, "unit": <string|null>,
          "applies_to": "BIDDER|OEM|BIDDER_OR_OEM|SUCCESSFUL_BIDDER|SELLER|BUYER|UNKNOWN",
          "risk_flags": ["RESTRICTIVE", ...],
          "ambiguity": "<what is unclear>"|null,
          "evidence": [{"chunk_id": "C3", "quote": "<verbatim text from that chunk>"}]
        }
      ],
      "ambiguities": [{"description": "...", "evidence": [{"chunk_id": "C3", "quote": "..."}]}]
    }

Validation is two-level:
  * envelope (strict, ``extra="forbid"``) - a broken envelope rejects the whole response;
  * each requirement / ambiguity individually - an invalid item is rejected and
    recorded (``rejected_json``) while valid items are kept.
Free-form enumerations from the model are mapped onto the controlled vocabularies
(unknown requirement type -> OTHER, unknown level -> UNKNOWN, ...); the model's
original label is kept for audit.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.ai.constants import APPLIES_TO, OBLIGATION_LEVELS, REQUIREMENT_TYPES, RISK_FLAGS

MAX_REQUIREMENTS = 100
MAX_AMBIGUITIES = 50

_TYPE_SYNONYMS = {
    "ISO_CERTIFICATION": "ISO", "ISO_CERTIFICATE": "ISO", "BIS": "CERTIFICATE", "CERTIFICATION": "CERTIFICATE",
    "OEM_AUTHORISATION": "OEM_AUTHORIZATION", "OEM": "OEM_AUTHORIZATION", "MAF": "MANUFACTURER_AUTHORIZATION",
    "MANUFACTURER_AUTHORISATION": "MANUFACTURER_AUTHORIZATION", "PERFORMANCE_SECURITY": "EPBG", "PBG": "EPBG",
    "E_PBG": "EPBG", "BID_SECURITY": "EMD", "EARNEST_MONEY_DEPOSIT": "EMD", "TECHNICAL": "TECHNICAL_SPECIFICATION",
    "SPECIFICATION": "TECHNICAL_SPECIFICATION", "SAMPLE": "SAMPLE_REQUIREMENT", "SAMPLES": "SAMPLE_REQUIREMENT",
    "DEMO": "DEMONSTRATION", "AFTER_SALES_SERVICE": "SERVICE_SUPPORT", "SERVICE": "SERVICE_SUPPORT",
    "MAINTENANCE": "AMC", "DOCUMENT": "DOCUMENT_SUBMISSION", "DOCUMENTS": "DOCUMENT_SUBMISSION",
    "DOCUMENTATION": "DOCUMENT_SUBMISSION", "ATC": "BUYER_ATC", "MAKE_IN_INDIA": "MII",
    "PURCHASE_PREFERENCE": "MSE", "PAST_EXPERIENCE": "EXPERIENCE", "FINANCIAL_TURNOVER": "TURNOVER",
}


def _enum_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").strip().upper()).strip("_")


def map_requirement_type(raw: Any) -> tuple[str, str | None]:
    """-> (taxonomy value, original label when it was mapped/unknown)."""
    key = _enum_key(raw)
    if key in REQUIREMENT_TYPES:
        return key, None
    if key in _TYPE_SYNONYMS:
        return _TYPE_SYNONYMS[key], str(raw)[:80]
    return "OTHER", (str(raw)[:80] if raw else None)


def map_level(raw: Any) -> str:
    key = _enum_key(raw)
    return key if key in OBLIGATION_LEVELS else "UNKNOWN"


def map_applies_to(raw: Any) -> str:
    key = _enum_key(raw)
    return key if key in APPLIES_TO else "UNKNOWN"


def map_risks(raw: list[Any]) -> list[str]:
    out: list[str] = []
    for r in raw:
        k = _enum_key(r)
        k = k if k in RISK_FLAGS else "OTHER"
        if k not in out:
            out.append(k)
    return out


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    chunk_id: str = Field(min_length=1, max_length=16)
    quote: str = Field(min_length=1, max_length=1200)


class RequirementItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    requirement_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=2000)
    obligation: str | None = Field(default=None, max_length=2000)
    obligation_level: str = Field(min_length=1, max_length=32)
    mandatory: bool | None = None
    condition: str | None = Field(default=None, max_length=1500)
    value: str | float | int | None = None
    unit: str | None = Field(default=None, max_length=32)
    applies_to: str | None = Field(default=None, max_length=32)
    risk_flags: list[str] = Field(default_factory=list, max_length=10)
    ambiguity: str | None = Field(default=None, max_length=1500)
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=8)

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return v.strip()[:500] or None
        if isinstance(v, (int, float)) and not math.isfinite(float(v)):
            raise ValueError("value must be finite")
        return v


class AmbiguityItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str = Field(min_length=1, max_length=1500)
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=8)


class Envelope(BaseModel):
    """Top-level shape. Items stay raw here and are validated one by one."""
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=4000)
    requirements: list[Any] = Field(default_factory=list, max_length=500)
    ambiguities: list[Any] = Field(default_factory=list, max_length=500)


class ResponseInvalid(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S | re.I)


def _reject_constant(name: str):
    raise ValueError(f"non-finite number {name} is not allowed")


def parse_envelope(text: str) -> Envelope:
    """Raw model text -> Envelope. Raises ResponseInvalid(MALFORMED_JSON | SCHEMA_VALIDATION_FAILED)."""
    if text is None or not str(text).strip():
        raise ResponseInvalid("EMPTY_RESPONSE", "empty response")
    s = str(text).strip()
    m = _FENCE.match(s)
    if m:
        s = m.group(1)
    if len(s) > 2_000_000:
        raise ResponseInvalid("MALFORMED_JSON", "response too large")
    try:
        data = json.loads(s, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:   # JSONDecodeError, huge ints, NaN/Infinity, deep nesting
        detail = f"{getattr(exc, 'msg', type(exc).__name__)}"
        pos = getattr(exc, "pos", None)
        raise ResponseInvalid("MALFORMED_JSON", f"response is not valid JSON: {detail}"
                              + (f" at pos {pos}" if pos is not None else "")) from None
    if not isinstance(data, dict):
        raise ResponseInvalid("SCHEMA_VALIDATION_FAILED", "top-level JSON value must be an object")
    try:
        return Envelope.model_validate(data)
    except ValidationError as exc:
        raise ResponseInvalid("SCHEMA_VALIDATION_FAILED", _short_errors(exc)) from None


def validate_requirement(raw: Any) -> RequirementItem:
    return RequirementItem.model_validate(raw)


def validate_ambiguity(raw: Any) -> AmbiguityItem:
    return AmbiguityItem.model_validate(raw)


def _short_errors(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors()[:5]:
        loc = ".".join(str(x) for x in e.get("loc", ()))
        parts.append(f"{loc}: {e.get('msg')}")
    return "; ".join(parts)[:500]


def short_errors(exc: ValidationError) -> str:
    return _short_errors(exc)


def output_schema_description() -> str:
    """Compact schema text embedded in the prompt (kept in sync with the models above)."""
    return json.dumps({
        "summary": "string (concise neutral summary of what the tender asks for; no eligibility verdicts)",
        "requirements": [{
            "requirement_type": "one of: " + ", ".join(REQUIREMENT_TYPES),
            "title": "short title",
            "summary": "what the clause means, in plain words",
            "obligation": "what has to be done/provided, by whom, when",
            "obligation_level": "one of: " + ", ".join(OBLIGATION_LEVELS),
            "condition": "when the requirement applies (required for CONDITIONAL), else null",
            "value": "number or short text stated in the evidence (e.g. 5, '25%'), else null",
            "unit": "e.g. YEARS, MONTHS, DAYS, PERCENT, INR, else null",
            "applies_to": "one of: " + ", ".join(APPLIES_TO),
            "risk_flags": "list, each one of: " + ", ".join(RISK_FLAGS),
            "ambiguity": "what is unclear or contradictory, else null",
            "evidence": [{"chunk_id": "an id from evidence_chunks", "quote": "verbatim text copied from that chunk"}],
        }],
        "ambiguities": [{"description": "unclear / contradictory clause", "evidence": [{"chunk_id": "...",
                                                                                       "quote": "..."}]}],
    }, indent=1)
