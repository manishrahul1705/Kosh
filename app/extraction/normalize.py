"""Deterministic, conservative text normalization.

The goal is *faithful* text: only whitespace, invisible characters and parser
artifacts are touched. Letters, digits, punctuation, currency symbols, %,
dates and wording are never changed, reordered or paraphrased.

Rules, applied in order:
 1. Unicode NFC (canonical composition only - NOT NFKC, which would rewrite
    characters such as "½" or superscripts).
 2. CRLF / CR -> LF.
 3. Parser artifact "(cid:N)" (glyph without a Unicode mapping, common in the
    Hindi parts of GeM PDFs) -> U+FFFD, so the gap stays visible but compact.
 4. NBSP and other Unicode space separators, and TAB -> " ".
 5. Remove invisible format characters that carry no content: zero-width space
    (U+200B), BOM (U+FEFF), soft hyphen (U+00AD), word joiner (U+2060), and C0/C1
    control characters except LF. ZWJ/ZWNJ (U+200D/U+200C) are KEPT - they are
    meaningful in Devanagari.
 6. Collapse runs of spaces to one; strip spaces at both ends of each line.
 7. Collapse 3+ consecutive newlines to 2 (at most one blank line).
 8. Strip leading/trailing whitespace of the whole text.
"""

from __future__ import annotations

import re
import unicodedata

CID_PATTERN = re.compile(r"\(cid:\d+\)")
REPLACEMENT = "�"
_REMOVE = {"​", "﻿", "­", "⁠"}
_SPACES = re.compile(r"[ ]{2,}")
_BLANKS = re.compile(r"\n{3,}")


def count_unmapped_glyphs(text: str | None) -> int:
    return len(CID_PATTERN.findall(text or ""))


def _clean_char(ch: str) -> str:
    if ch == "\n":
        return ch
    if ch in _REMOVE:
        return ""
    if ch == "\t":
        return " "
    cat = unicodedata.category(ch)
    if cat == "Zs":
        return " "
    if cat == "Cc":
        return ""
    return ch


def normalize_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CID_PATTERN.sub(REPLACEMENT, text)
    text = "".join(_clean_char(c) for c in text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANKS.sub("\n\n", text)
    return text.strip()


def normalize_cell(raw: str | None) -> str | None:
    """Table cell: same rules; None (empty/merged cell) stays None. Line breaks
    inside a cell are kept (they are layout wraps, but may also separate items)."""
    if raw is None:
        return None
    return normalize_text(raw)


def word_count(text: str) -> int:
    return len(text.split()) if text else 0


def meaningful_char_count(text: str) -> int:
    """Letters and digits only (U+FFFD and punctuation excluded)."""
    return sum(1 for c in text if c.isalnum())
