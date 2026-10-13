"""Deterministic value normalizers. Pure functions; the raw source text is never changed.

Each normalizer returns a ``Normalized`` (typed value + canonical comparison key)
or a ``Rejected`` explaining why the source value carries no usable fact
(masked "*****", "N/a", or not parseable as the field's type). Rejected values
make a field UNKNOWN - never FALSE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from app.fields.constants import Reason, TriState, ValueType


@dataclass
class Normalized:
    value: object                  # JSON-serializable normalized value
    key: str                       # canonical comparison key (equal key == same fact)
    text: str | None               # canonical text (value_text column)
    number: float | None = None
    unit: str | None = None
    tri_state: str | None = None
    details: dict = field(default_factory=dict)


@dataclass
class Rejected:
    reason: str


Result = Normalized | Rejected

_WS = re.compile(r"\s+")
_MASK = re.compile(r"^\*{3,}$")
_NA = {"n/a", "na", "n.a.", "n.a", "not applicable", "nil", "-", "--", "none"}


def clean(raw: str | None) -> str:
    return _WS.sub(" ", raw or "").strip()


def precheck(raw: str | None) -> Rejected | None:
    s = clean(raw)
    if not s:
        return Rejected(Reason.NOT_FOUND.value)
    if _MASK.match(s):
        return Rejected(Reason.MASKED_IN_SOURCE.value)
    if s.lower() in _NA:
        return Rejected(Reason.NOT_APPLICABLE_IN_SOURCE.value)
    return None


# --- text ------------------------------------------------------------------
def norm_text(raw: str) -> Result:
    bad = precheck(raw)
    if bad:
        return bad
    s = clean(raw)
    return Normalized(s, "t:" + s.casefold(), s)


# --- booleans (three-state) -------------------------------------------------
_TRUE_WORDS = ("yes", "required", "applicable", "mandatory", "true", "enabled")
_FALSE_WORDS = ("no", "not required", "not applicable", "false", "disabled", "not mandatory")


def norm_bool(raw: str) -> Result:
    """'Yes' / 'Yes | Complete' / 'Yes (Documents ...)' -> TRUE; 'No' / 'Not Required' -> FALSE.

    Only the leading word(s) decide; anything else is UNPARSEABLE (never guessed).
    "N/a" stays UNKNOWN (NOT_APPLICABLE_IN_SOURCE) rather than FALSE.
    """
    s = clean(raw)
    if _MASK.match(s) or not s:
        return precheck(raw) or Rejected(Reason.UNPARSEABLE.value)
    low = s.lower()
    lead = re.split(r"[|(,;:]", low, maxsplit=1)[0].strip()
    detail = s[len(lead):].strip(" |(),;:") or None
    if lead in _FALSE_WORDS:
        return Normalized(False, "b:FALSE", "FALSE", tri_state=TriState.FALSE.value,
                          details={"qualifier": detail} if detail else {})
    if lead in _TRUE_WORDS:
        return Normalized(True, "b:TRUE", "TRUE", tri_state=TriState.TRUE.value,
                          details={"qualifier": detail} if detail else {})
    if low in _NA:
        return Rejected(Reason.NOT_APPLICABLE_IN_SOURCE.value)
    return Rejected(Reason.UNPARSEABLE.value)


# --- numbers ------------------------------------------------------------------
_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?")


def _to_decimal(int_part: str, frac: str | None) -> Decimal:
    return Decimal(int_part.replace(",", "") + (frac or ""))


def _num_text(d: Decimal) -> str:
    q = d.normalize()
    return format(q, "f") if q == q.to_integral() or "E" not in str(q) else str(q)


def norm_integer(raw: str) -> Result:
    """'155 (Days)' -> 155; '2' -> 2. The FIRST number only; '2.5' is UNPARSEABLE."""
    bad = precheck(raw)
    if bad:
        return bad
    m = _NUM.search(clean(raw))
    if not m or m.group(2):
        return Rejected(Reason.UNPARSEABLE.value)
    n = int(m.group(1).replace(",", ""))
    return Normalized(n, f"n:{n}", str(n), number=float(n))


def norm_percent(raw: str) -> Result:
    """'10 %' -> 10; '5.00' -> 5 (labels such as 'ePBG Percentage(%)' state the unit)."""
    bad = precheck(raw)
    if bad:
        return bad
    s = clean(raw)
    m = _NUM.search(s)
    if not m:
        return Rejected(Reason.UNPARSEABLE.value)
    d = _to_decimal(m.group(1), m.group(2))
    if d > 100:
        return Rejected(Reason.UNPARSEABLE.value)
    t = _num_text(d)
    return Normalized(float(d), f"p:{t}", t, number=float(d), unit="PERCENT")


_MULT = (
    (re.compile(r"\b(crore|crores|cr)\b\.?", re.I), Decimal(10_000_000), "CRORE"),
    (re.compile(r"\b(lakh|lakhs|lac|lacs)\b\s*(\(\s*s\s*\))?", re.I), Decimal(100_000), "LAKH"),
    (re.compile(r"\bthousand\b", re.I), Decimal(1_000), "THOUSAND"),
)
_CURRENCY = re.compile(r"(₹|\bRs\.?|\bINR\b|\bRupees?\b)", re.I)


def norm_money(raw: str, currency_hint: str | None = None) -> Result:
    """'₹ 50,000' / 'Rs. 50000' / 'INR 50,000' -> 50000 INR; '20 Lakh (s)' -> 2000000.

    Currency is recorded only when the value or its label states it explicitly
    (``currency_hint``); otherwise it is left null (not assumed).
    """
    bad = precheck(raw)
    if bad:
        return bad
    s = clean(raw)
    m = _NUM.search(s)
    if not m:
        return Rejected(Reason.UNPARSEABLE.value)
    try:
        d = _to_decimal(m.group(1), m.group(2))
    except InvalidOperation:  # pragma: no cover
        return Rejected(Reason.UNPARSEABLE.value)
    scale, scale_name = Decimal(1), None
    for pat, mult, name in _MULT:
        if pat.search(s):
            scale, scale_name = mult, name
            break
    amount = d * scale
    currency = "INR" if _CURRENCY.search(s) else currency_hint
    t = _num_text(amount)
    details = {"amount": float(amount), "currency": currency, "stated_number": float(d)}
    if scale_name:
        details["stated_unit"] = scale_name
    return Normalized(details, f"m:{t}", t, number=float(amount), unit=currency, details={})


# --- durations ------------------------------------------------------------------
_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*\(?\s*(years?|yrs?|months?|days?|weeks?)\s*(?:\(\s*s\s*\))?\)?", re.I)
_UNIT = {"y": "YEARS", "m": "MONTHS", "d": "DAYS", "w": "WEEKS"}


def norm_duration(raw: str, default_unit: str | None = None) -> Result:
    """'2 Days' -> 2 DAYS; '155 (Days)'; '2 Year (s)'; '1.0 (year)'; '1 Year(s) 1 Day(s)'
    -> compound. A bare number uses ``default_unit`` only when the LABEL states it
    (e.g. 'Duration of ePBG required (Months)')."""
    bad = precheck(raw)
    if bad:
        return bad
    s = clean(raw)
    parts = [(Decimal(n), _UNIT[u[0].lower()]) for n, u in _DUR.findall(s)]
    if not parts:
        m = _NUM.fullmatch(s) or _NUM.match(s)
        if m and default_unit and not m.group(2) and m.end() == len(s):
            parts = [(Decimal(m.group(1).replace(",", "")), default_unit)]
        else:
            return Rejected(Reason.UNPARSEABLE.value)
    norm = [{"value": float(v), "unit": u} for v, u in parts]
    text = " ".join(f"{_num_text(v)} {u}" for v, u in parts)
    if len(parts) == 1:
        v, u = parts[0]
        return Normalized(norm[0], f"d:{_num_text(v)}:{u}", text, number=float(v), unit=u)
    return Normalized({"parts": norm}, "d:" + text, text)


# --- dates ------------------------------------------------------------------
_DT = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\b")


def norm_datetime(raw: str, zone: str, date_only: bool = False) -> Result:
    """'16-10-2026 21:00:00' (DD-MM-YYYY, document wall clock in ``zone``) ->
    {"local": "2026-10-16T21:00:00+05:30", "utc": "2026-10-16T15:30:00Z"}."""
    bad = precheck(raw)
    if bad:
        return bad
    m = _DT.search(clean(raw))
    if not m:
        return Rejected(Reason.UNPARSEABLE.value)
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        if date_only or m.group(4) is None:
            d = datetime(year, month, day).date()
            return Normalized({"date": d.isoformat()}, f"date:{d.isoformat()}", d.isoformat())
        local = datetime(year, month, day, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0),
                         tzinfo=ZoneInfo(zone))
    except ValueError:
        return Rejected(Reason.UNPARSEABLE.value)
    utc = local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    utc_iso = utc.isoformat(timespec="seconds") + "Z"
    return Normalized({"local": local.isoformat(timespec="seconds"), "utc": utc_iso, "timezone": zone},
                      f"dt:{utc_iso}", utc_iso)


# --- lists ------------------------------------------------------------------
def norm_list(items: list[str]) -> Result:
    seen, out = set(), []
    for it in items:
        c = clean(it)
        if c and c.casefold() not in seen:
            seen.add(c.casefold())
            out.append(c)
    if not out:
        return Rejected(Reason.NOT_FOUND.value)
    return Normalized(out, "l:" + "|".join(sorted(x.casefold() for x in out)), " | ".join(out))


def normalize(value_type: str, raw: str, *, zone: str = "Asia/Kolkata", default_unit: str | None = None,
              currency_hint: str | None = None) -> Result:
    if value_type == ValueType.TEXT.value:
        return norm_text(raw)
    if value_type == ValueType.BOOL.value:
        return norm_bool(raw)
    if value_type == ValueType.INTEGER.value:
        return norm_integer(raw)
    if value_type == ValueType.PERCENT.value:
        return norm_percent(raw)
    if value_type == ValueType.MONEY.value:
        return norm_money(raw, currency_hint)
    if value_type == ValueType.DURATION.value:
        return norm_duration(raw, default_unit)
    if value_type == ValueType.DATETIME.value:
        return norm_datetime(raw, zone)
    if value_type == ValueType.DATE.value:
        return norm_datetime(raw, zone, date_only=True)
    raise ValueError(f"no scalar normalizer for {value_type}")
