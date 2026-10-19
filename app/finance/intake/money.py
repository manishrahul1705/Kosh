"""Exact INR text parsing to integer paise."""
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
import re

_NUMBER=re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w.])")
_SCALE={"lakh":Decimal(100000),"lakhs":Decimal(100000),"lac":Decimal(100000),"crore":Decimal(10000000),"crores":Decimal(10000000)}

def parse_inr_to_paise(text:str)->tuple[int|None,str|None]:
    raw=" ".join(str(text or "").split());low=raw.lower()
    if not raw:return None,"EMPTY"
    if re.search(r"\b(?:usd|eur|gbp|dollar|euro)\b|[$€£]",raw,re.I):return None,"UNSUPPORTED_CURRENCY"
    if re.search(r"(?:-|–|to)\s*(?:rs\.?|inr|₹)?\s*\d",raw,re.I):return None,"RANGE_OR_NEGATIVE"
    matches=list(_NUMBER.finditer(raw))
    if len(matches)!=1:return None,"MULTIPLE_OR_MISSING_AMOUNTS"
    try:value=Decimal(matches[0].group(1).replace(",",""))
    except InvalidOperation:return None,"INVALID_AMOUNT"
    tail=low[matches[0].end():].strip(" .()/-")
    scale=Decimal(1)
    for name,mult in _SCALE.items():
        if re.match(rf"^{name}\b",tail):scale=mult;break
    value*=scale
    if value<0:return None,"NEGATIVE_AMOUNT"
    paise=(value*100).quantize(Decimal("1"),rounding=ROUND_HALF_UP)
    if paise!=value*100:return None,"FRACTIONAL_PAISE"
    return int(paise),None
