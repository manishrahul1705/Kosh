"""PDF parsing with pdfplumber (MIT licence; built on pdfminer.six).

Page by page, so memory stays bounded. For each page we produce:
  * raw_text      pdfplumber text of the page after removing *overprinted duplicate
                  glyphs* (wkhtmltopdf draws bold text twice, which otherwise yields
                  "बबडड"/"//Bid"). No other change is made to the parser output.
  * tables        ruled tables ("lines" strategy) as cell grids
  * lines         text lines with font size / bold ratio, for heading detection
  * image_count, page size, char-size histogram

Parser errors on one page do not abort the document: the page is recorded with
error_code PARSER_ERROR and extraction continues.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pdfminer
import pdfplumber

from app.core.logging import log_event
from app.extraction.constants import ErrorCode, ExtractionError
from app.extraction.normalize import normalize_cell, normalize_text

logger = logging.getLogger("app.extraction.pdf_parser")

LINE_TOLERANCE = 3.0  # points: words whose tops differ less belong to one line
DEDUPE_TOLERANCE = 1.0


def parser_version() -> str:
    return f"pdfplumber {pdfplumber.__version__}; pdfminer.six {getattr(pdfminer, '__version__', '?')}"


@dataclass
class TextLine:
    page_number: int
    text: str            # normalized line text
    top: float
    x0: float
    size: float          # dominant font size (Latin chars when present)
    bold_ratio: float    # share of (Latin) characters in a bold font
    in_table: bool
    word_count: int


@dataclass
class ParsedTable:
    page_number: int
    table_index: int     # 1-based within the page
    rows: list[list[str | None]]
    bbox: tuple[float, float, float, float]
    location: dict | None = None
    method: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return max((len(r) for r in self.rows), default=0)


@dataclass
class ParsedPage:
    page_number: int     # 1-based
    raw_text: str = ""
    width: float | None = None
    height: float | None = None
    image_count: int = 0
    image_area_ratio: float = 0.0
    tables: list[ParsedTable] = field(default_factory=list)
    lines: list[TextLine] = field(default_factory=list)
    char_sizes: Counter = field(default_factory=Counter)
    error_code: str | None = None
    error_message: str | None = None


def _is_bold(fontname: str | None) -> bool:
    name = (fontname or "").split("+")[-1].lower()
    return any(k in name for k in ("bold", "black", "heavy", "semibold", "demi"))


def _has_latin(text: str) -> bool:
    return any("a" <= c.lower() <= "z" for c in text)


def build_lines(words: list[dict], page_number: int, table_boxes: list[tuple]) -> list[TextLine]:
    """Group pdfplumber words (with fontname/size) into visual lines."""
    if not words:
        return []
    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    groups: list[list[dict]] = []
    anchor = None
    for w in words:
        if anchor is None or abs(w["top"] - anchor) > LINE_TOLERANCE:
            groups.append([w])
            anchor = w["top"]
        else:
            groups[-1].append(w)
    lines = []
    for g in groups:
        g.sort(key=lambda w: w["x0"])
        text = normalize_text(" ".join(w["text"] for w in g))
        if not text:
            continue
        latin = [w for w in g if _has_latin(w["text"])]
        basis = latin or g
        total = sum(len(w["text"]) for w in basis) or 1
        bold = sum(len(w["text"]) for w in basis if _is_bold(w.get("fontname")))
        size = max(basis, key=lambda w: len(w["text"])).get("size") or 0.0
        top = min(w["top"] for w in g)
        bottom = max(w["bottom"] for w in g)
        x0 = min(w["x0"] for w in g)
        x1 = max(w["x1"] for w in g)
        mid = (top + bottom) / 2
        in_table = any(bx0 - 1 <= x1 and x0 <= bx1 + 1 and btop - 1 <= mid <= bbottom + 1
                       for (bx0, btop, bx1, bbottom) in table_boxes)
        lines.append(TextLine(page_number=page_number, text=text, top=round(top, 2), x0=round(x0, 2),
                              size=round(float(size), 2), bold_ratio=round(bold / total, 3),
                              in_table=in_table, word_count=len(text.split())))
    return lines


def _clean_rows(rows: list[list]) -> list[list[str | None]]:
    """Normalize cell text; drop rows whose cells are all empty (ruling artifacts).
    Column positions are kept: an empty/merged cell stays null."""
    cleaned = [[normalize_cell(c) for c in row] for row in rows]
    return [row for row in cleaned if any(c for c in row)]


def _table_has_content(rows: list[list[str | None]]) -> bool:
    return any(c for row in rows for c in row)


class PdfPlumberParser:
    """Opens one PDF read-only and yields ParsedPage objects."""

    name = "pdfplumber"

    def __init__(self, tables_enabled: bool = True) -> None:
        self.tables_enabled = tables_enabled

    @staticmethod
    def _open(path: Path):
        try:
            return pdfplumber.open(str(path))
        except Exception as exc:  # classify pdfminer/pdfplumber failures
            raise classify_open_error(exc) from exc

    def page_count(self, path: Path) -> int:
        pdf = self._open(path)
        try:
            return len(pdf.pages)
        except Exception as exc:
            raise classify_open_error(exc) from exc
        finally:
            pdf.close()

    def iter_pages(self, path: Path, max_pages: int) -> Iterator[ParsedPage]:
        pdf = self._open(path)
        try:
            try:
                total = len(pdf.pages)
            except Exception as exc:
                raise classify_open_error(exc) from exc
            for index in range(min(total, max_pages)):
                yield self._parse_page(pdf, index)
        finally:
            pdf.close()

    def _parse_page(self, pdf, index: int) -> ParsedPage:
        number = index + 1
        result = ParsedPage(page_number=number)
        page = None
        try:
            page = pdf.pages[index]
            result.width, result.height = float(page.width), float(page.height)
            result.image_count = len(page.images)
            area=page.width*page.height
            if area>0:
                result.image_area_ratio=min(1.0,sum(
                    max(0,min(page.width,i.get('x1',0))-max(0,i.get('x0',0))) *
                    max(0,min(page.height,i.get('bottom',0))-max(0,i.get('top',0)))
                    for i in page.images[:1000])/area)
            d = page.dedupe_chars(tolerance=DEDUPE_TOLERANCE)
            result.raw_text = d.extract_text() or ""
            result.char_sizes = Counter(round(float(c.get("size") or 0), 1) for c in d.chars if c.get("text", "").strip())
            boxes: list[tuple] = []
            if self.tables_enabled:
                for table in d.find_tables():
                    rows = _clean_rows(table.extract())
                    if not _table_has_content(rows):
                        continue
                    boxes.append(tuple(table.bbox))
                    result.tables.append(ParsedTable(number, len(result.tables) + 1, rows,
                                                     tuple(round(v, 2) for v in table.bbox)))
            words = d.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False)
            result.lines = build_lines(words, number, boxes)
        except ExtractionError:
            raise
        except Exception as exc:
            if _is_password_error(exc):
                raise classify_open_error(exc) from exc
            result.error_code = ErrorCode.PARSER_ERROR.value
            result.error_message = f"{type(exc).__name__}: {exc}"[:500]
            result.raw_text = result.raw_text or ""
            log_event(logger, logging.WARNING, "page_extraction_failed", page=number,
                      error=type(exc).__name__)
        finally:
            if page is not None:
                try:
                    page.close()  # release cached objects: bounded memory per page
                except Exception:  # pragma: no cover
                    pass
        return result


def _is_password_error(exc: BaseException) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        name = type(exc).__name__
        if "Password" in name or "Encryption" in name:
            return True
        exc = exc.__cause__ or exc.__context__ or (exc.args[0] if exc.args and isinstance(exc.args[0], BaseException) else None)
    return False


def classify_open_error(exc: BaseException) -> ExtractionError:
    if isinstance(exc, ExtractionError):
        return exc
    if _is_password_error(exc):
        return ExtractionError(ErrorCode.PASSWORD_PROTECTED, "PDF is password protected / encrypted")
    if isinstance(exc, (FileNotFoundError,)):
        return ExtractionError(ErrorCode.FILE_MISSING, str(exc))
    if isinstance(exc, (PermissionError, IsADirectoryError)):
        return ExtractionError(ErrorCode.FILE_UNREADABLE, str(exc))
    return ExtractionError(ErrorCode.PDF_CORRUPT, f"PDF could not be parsed: {type(exc).__name__}: {exc}"[:500])
