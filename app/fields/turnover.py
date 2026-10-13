"""Evidence-based turnover amounts. Ambiguous amounts never become thresholds."""

import re
import math
from app.fields.normalizers import norm_money, Normalized

_SCALE = r"(?:lakhs?|lacs?|crores?|cr|thousand)"
_NUMBER = r"\d+(?:,\d{2,3})*(?:\.\d+)?"
_AMOUNT = re.compile(
    rf"(?<![\w.])(?:INR\s*|Rs\.?\s*|₹\s*)?{_NUMBER}\s*(?:{_SCALE}\b)?(?!\w|\.\d)", re.I
)


def turnover_amount(text, currency_hint=None):
    """Require one unambiguous turnover amount, including units stated in labels.

    Years in a label are not amounts. Multiple amounts/ranges require review.
    The model's value is never used to select a number from source evidence.
    """
    amounts = []
    for line in text.splitlines():
        if not re.search(r"\bturnover\b", line, re.I):
            continue
        if re.search(r"\b(?:up to|at most|maximum|less than|not more than|approximately|about)\b", line, re.I):
            return None
        if re.search(r"[$£€¥]|\b(?:USD|EUR|GBP|AUD|CAD|JPY|CNY|dollars?|euros?|pounds?|yen)\b", line, re.I):
            return None
        label, separator, value = line.rpartition(":")
        if not separator:
            label, separator, value = line.rpartition("|")
        if not separator:
            label, value = "", line
        matches = list(_AMOUNT.finditer(value))
        if len(matches) != 1 or re.search(r"[-−]\s*\d|\b(?:USD|EUR|dollars?|euros?)\b", value, re.I):
            return None
        raw = matches[0].group()
        # A verified quote can state the obligation without its monetary amount.
        # Calendar dates, accounting durations and percentages are not thresholds.
        after = value[matches[0].end():].lstrip()
        before = value[:matches[0].start()]
        if re.match(r"(?:%|percent\b|years?\b|months?\b|days?\b|"
                    r"Jan(?:uary)?\b|Feb(?:ruary)?\b|Mar(?:ch)?\b|Apr(?:il)?\b|May\b|"
                    r"Jun(?:e)?\b|Jul(?:y)?\b|Aug(?:ust)?\b|Sep(?:tember)?\b|"
                    r"Oct(?:ober)?\b|Nov(?:ember)?\b|Dec(?:ember)?\b)", after, re.I) \
                or re.search(r"\b(?:year|FY)\s*$", before, re.I):
            return None
        if re.search(rf"\b{_SCALE}\b", value[matches[0].end():], re.I):
            return None
        label_scales = re.findall(rf"\b{_SCALE}\b", label, re.I)
        raw_scales = re.findall(rf"\b{_SCALE}\b", raw, re.I)
        if label_scales:
            scales = {norm_money("1 " + s).number for s in label_scales + raw_scales}
            if len(scales) != 1:
                return None
        if label_scales and not re.search(rf"\b{_SCALE}\b", raw, re.I):
            if len(label_scales) != 1:
                return None
            raw += " " + label_scales[0]
        hint = "INR" if re.search(r"\bINR\b|₹|\bRs\b", label, re.I) else currency_hint
        amount = norm_money(raw, hint)
        if not isinstance(amount, Normalized) or not math.isfinite(amount.number):
            return None
        amounts.append(amount)
    if not amounts or len({(a.number, a.unit) for a in amounts}) != 1:
        return None
    return amounts[0]
