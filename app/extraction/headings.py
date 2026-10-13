"""Deterministic heading / section detection from font-annotated text lines.

Input: TextLine objects (see pdf_parser) and the document's body font size
(the most common character size). A line becomes a heading only when one of
these rules fires (first match wins); otherwise nothing is invented.

  known_heading  English part of the line matches a known GeM section title
                 (exactly, or as a prefix outside tables when the line is not a
                 sentence ending in "."). Inside a ruled table
                 only an EXACT match counts, so key/value rows such as
                 "MSE Purchase Preference | Yes" are never headings.
  font_size      outside tables, font >= 1.15 x body size and (mostly bold or
                 >= 1.3 x body size).
  numbered       (checked first) outside tables, "1." / "2.3" / "4)" + text,
                 >= 80 % bold, <= 12 words, not ending with ".", no "label: value"
  bold_line      outside tables, >= 90 % bold, 1-10 words, starts with a capital,
                 not ending with "." or ":", no "label: value"
  uppercase      outside tables, >= 4 letters, >= 90 % uppercase letters,
                 <= 8 words, not ending with ":"

Common guards: 3+ letters, <= 15 words, <= 150 chars, not ending with "," or ";".
Levels: font-size headings are ranked by size (largest = 1, max 3); known
headings use their size rank when larger than body text, else 2; numbered use
their depth (1. -> 2, 1.1 -> 3); bold_line / uppercase -> 3.

Bilingual GeM lines ("<Hindi>/Bid Details") are reduced to their trailing
English part for matching and for ``normalized_heading``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.extraction.normalize import REPLACEMENT
from app.extraction.pdf_parser import TextLine

KNOWN_GEM_HEADINGS: tuple[str, ...] = (
    "bid document", "bid details", "buyer details", "emd detail", "emd details", "epbg detail",
    "epbg details", "mii purchase preference", "mse purchase preference", "technical specifications",
    "technical specification", "consignees reporting officer", "consignees reporting officer and quantity",
    "buyer added bid specific terms and conditions", "buyer added bid specific atc",
    "additional terms and conditions", "scope of work", "service level agreement", "eligibility criteria",
    "pre qualification criteria", "evaluation method", "payment terms", "delivery period",
    "warranty", "disclaimer", "bid splitting", "splitting", "past performance", "bidder turnover",
    "general terms and conditions", "special terms and conditions", "item details", "boq", "documents required",
)

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3})[.)]?\s+[A-Za-z]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass
class Heading:
    page_number: int
    sequence: int
    heading: str
    normalized_heading: str
    heading_level: int | None
    detection_method: str
    top: float
    char_offset: int | None = None


def english_part(text: str) -> str:
    """The whole line if it has no Devanagari/U+FFFD, else its trailing run that has none."""
    if not _DEVANAGARI.search(text) and REPLACEMENT not in text:
        return text.strip()
    for i, ch in enumerate(text):
        if ch.isascii() and ch.isalpha():
            rest = text[i:]
            if not _DEVANAGARI.search(rest) and REPLACEMENT not in rest:
                return rest.strip()
    return ""


_LEADING_NUMBER = re.compile(r"^\s*[/(]?\d+(?:\.\d+){0,3}[.)]?\s+")


def normalize_heading(text: str) -> str:
    """Lower-case English part without clause numbering/punctuation ("3. Warranty" -> "warranty")."""
    base = english_part(text) or text.replace(REPLACEMENT, " ")
    base = _LEADING_NUMBER.sub("", base.lstrip("/ "))
    return _NON_ALNUM.sub(" ", base.lower()).strip()[:255]


def _letters(text: str) -> list[str]:
    return [c for c in text if c.isalpha()]


def _known(norm: str, in_table: bool, sentence: bool) -> bool:
    for k in KNOWN_GEM_HEADINGS:
        if norm == k:
            return True
        if (not in_table and not sentence and norm.startswith(k + " ")
                and len(norm.split()) <= len(k.split()) + 3):
            return True
    return False


_LABEL_VALUE = re.compile(r":\s*\S")  # "Bid Number: GEM/..." is a key/value line, not a heading


def _rule(line: TextLine, body: float) -> tuple[str, int | None] | None:
    text = line.text
    eng = english_part(text)
    basis = eng or text
    letters = _letters(basis)
    if len(letters) < 3 or line.word_count > 15 or len(text) > 150 or text.endswith((",", ";")):
        return None
    norm = normalize_heading(text)
    sentence = basis.endswith(".")
    numbered = _NUMBERED.match(basis.lstrip("/ "))
    if (numbered and not line.in_table and line.bold_ratio >= 0.8 and line.word_count <= 12
            and not sentence and not _LABEL_VALUE.search(basis)):
        return "numbered", min(3, numbered.group(1).count(".") + 2)
    if norm and line.word_count <= 12 and _known(norm, line.in_table, sentence):
        return "known_heading", None
    if line.in_table:
        return None
    if body > 0 and line.size >= body * 1.15 and (line.bold_ratio >= 0.5 or line.size >= body * 1.3):
        return "font_size", None
    if _LABEL_VALUE.search(basis):
        return None
    words = len(basis.split())
    first_alpha = next((c for c in basis if c.isalpha()), "")
    if (line.bold_ratio >= 0.9 and 1 <= words <= 10 and not basis.endswith((".", ":"))
            and first_alpha.isupper()):
        return "bold_line", 3
    upper = [c for c in letters if c.isupper()]
    if len(letters) >= 4 and len(upper) / len(letters) >= 0.9 and words <= 8 and not basis.endswith(":"):
        return "uppercase", 3
    return None


def body_font_size(char_sizes) -> float:
    """Most common character size (Counter of size -> count)."""
    if not char_sizes:
        return 0.0
    return float(max(char_sizes.items(), key=lambda kv: (kv[1], -kv[0]))[0])


def detect_headings(lines: list[TextLine], body_size: float) -> list[Heading]:
    found: list[tuple[TextLine, str, int | None]] = []
    for line in lines:
        rule = _rule(line, body_size)
        if rule:
            found.append((line, rule[0], rule[1]))

    big_sizes = sorted({round(l.size, 1) for l, m, _ in found
                        if m in ("font_size", "known_heading") and l.size > body_size * 1.05}, reverse=True)
    rank = {s: min(3, i + 1) for i, s in enumerate(big_sizes)}

    headings: list[Heading] = []
    seen: set[tuple[int, str, int]] = set()
    for line, method, level in found:
        norm = normalize_heading(line.text)
        key = (line.page_number, norm, int(line.top // 3))
        if not norm or key in seen:
            continue
        seen.add(key)
        if method in ("font_size", "known_heading"):
            level = rank.get(round(line.size, 1), 2 if method == "known_heading" else 1)
        headings.append(Heading(page_number=line.page_number, sequence=len(headings) + 1, heading=line.text,
                                normalized_heading=norm, heading_level=level, detection_method=method,
                                top=line.top))
    return headings


def locate_offsets(headings: list[Heading], page_texts: dict[int, str]) -> None:
    """Set char_offset = position of the heading text in its page's normalized text."""
    cursor: dict[int, int] = {}
    for h in headings:
        text = page_texts.get(h.page_number) or ""
        needle = english_part(h.heading) or h.heading
        pos = text.find(needle, cursor.get(h.page_number, 0))
        if pos < 0:
            pos = text.find(needle)
        h.char_offset = pos if pos >= 0 else None
        if pos >= 0:
            cursor[h.page_number] = pos + len(needle)
