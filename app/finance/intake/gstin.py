"""GSTIN syntax and base-36 check-character validation."""
import re
_CHARS="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def validate_gstin(value:str|None)->bool:
    text=(value or "").strip().upper()
    if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]",text):return False
    factor,total=1,0
    for char in text[:-1]:
        code=_CHARS.index(char);product=code*factor;total+=product//36+product%36;factor=2 if factor==1 else 1
    return _CHARS[(36-total%36)%36]==text[-1]
