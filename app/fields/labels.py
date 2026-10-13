"""Label normalization and alias matching (bilingual GeM labels).

GeM labels look like ``"<Hindi with U+FFFD gaps>/Bid End Date/Time"`` and may be
wrapped over several lines. We keep the trailing ENGLISH part (same rule as
Stage 3A heading detection) and reduce it to a key: lower-case, every run of
non-alphanumerics -> one space.  "ePBG Percentage(%)" -> "epbg percentage".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.extraction.headings import english_part

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def english_label(cell: str | None) -> str:
    """English part of a (possibly bilingual, multi-line) label cell."""
    if not cell:
        return ""
    one_line = " ".join(cell.split())
    eng = english_part(one_line) or one_line
    return eng.strip(" /:-")


def label_key(text: str | None) -> str:
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


@dataclass(frozen=True)
class Alias:
    """``mode``: exact (whole key equal) | prefix (key starts with alias words) |
    contains (alias words appear contiguously; only for long distinctive phrases)."""

    text: str
    mode: str = "exact"

    @property
    def key(self) -> str:
        return label_key(self.text)

    def matches(self, key: str) -> bool:
        a = self.key
        if self.mode == "exact":
            return key == a
        if self.mode == "prefix":
            return key == a or key.startswith(a + " ")
        if self.mode == "contains":
            return f" {a} " in f" {key} "
        raise ValueError(self.mode)


def exact(*texts: str) -> tuple[Alias, ...]:
    return tuple(Alias(t, "exact") for t in texts)


def prefix(*texts: str) -> tuple[Alias, ...]:
    return tuple(Alias(t, "prefix") for t in texts)


def contains(*texts: str) -> tuple[Alias, ...]:
    return tuple(Alias(t, "contains") for t in texts)


def alias_regex(alias: Alias) -> re.Pattern:
    """Regex matching the alias words at the START of an English text line,
    tolerant to punctuation/spacing between words (for page-text label lines)."""
    words = alias.key.split()
    return re.compile(r"^\W*" + r"\W+".join(map(re.escape, words)) + r"\b\W*", re.I)
