"""Deterministic extraction quality classification (no AI, no fake confidence).

Per page:  has_text  := meaningful_chars >= EXTRACTION_MIN_PAGE_CHARS
           (meaningful_chars = letters + digits of the normalized text; U+FFFD,
           punctuation and whitespace excluded)
           needs_ocr := not has_text and page has >= 1 image (and no parser error)
           blank     := not has_text and no image and no parser error

Document (n = pages parsed, T = pages with text, S = pages needing OCR, E = pages
with parser errors, truncated = more pages than EXTRACTION_MAX_PAGES):

  n == 0                         -> FAILED  / quality FAILED   (PDF_CORRUPT: no pages)
  E == n                         -> FAILED  / quality FAILED   (PARSER_ERROR)
  T == 0 and S == 0              -> OCR_REQUIRED / quality EMPTY / text_class EMPTY
  T == 0 or S > T                -> OCR_REQUIRED / quality OCR_REQUIRED / LIKELY_SCANNED
  E == 0, S == 0, not truncated  -> SUCCESS / quality GOOD
                                    (text_class TEXT_NATIVE if T == n, else TEXT_PARTIAL:
                                     only blank pages are missing text)
  otherwise                      -> PARTIAL_SUCCESS / quality PARTIAL / TEXT_PARTIAL
                                    (error_code PAGE_ERRORS | PAGE_LIMIT | PAGES_NEED_OCR)

text_coverage_ratio := T / n (0 when n == 0).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.extraction.constants import ErrorCode, ExtractionStatus, QualityStatus, TextClass


@dataclass
class PageQuality:
    has_text: bool
    image_count: int
    error: bool


@dataclass
class QualityResult:
    status: str
    quality: str
    text_class: str
    coverage: float
    error_code: str | None = None
    message: str | None = None


def classify(pages: list[PageQuality], truncated: bool = False) -> QualityResult:
    n = len(pages)
    if n == 0:
        return QualityResult(ExtractionStatus.FAILED.value, QualityStatus.FAILED.value, TextClass.EMPTY.value,
                             0.0, ErrorCode.PDF_CORRUPT.value, "PDF has no pages")
    t = sum(p.has_text for p in pages)
    e = sum(p.error for p in pages)
    s = sum(1 for p in pages if not p.has_text and not p.error and p.image_count > 0)
    coverage = round(t / n, 4)
    if e == n:
        return QualityResult(ExtractionStatus.FAILED.value, QualityStatus.FAILED.value, TextClass.EMPTY.value,
                             coverage, ErrorCode.PARSER_ERROR.value, "Every page failed to parse")
    if t == 0 and s == 0:
        return QualityResult(ExtractionStatus.OCR_REQUIRED.value, QualityStatus.EMPTY.value, TextClass.EMPTY.value,
                             coverage, ErrorCode.OCR_REQUIRED.value, "No extractable text and no images")
    if t == 0 or s > t:
        return QualityResult(ExtractionStatus.OCR_REQUIRED.value, QualityStatus.OCR_REQUIRED.value,
                             TextClass.LIKELY_SCANNED.value, coverage, ErrorCode.OCR_REQUIRED.value,
                             f"{s} of {n} page(s) are images without a text layer")
    text_class = TextClass.TEXT_NATIVE.value if t == n else TextClass.TEXT_PARTIAL.value
    if e == 0 and s == 0 and not truncated:
        return QualityResult(ExtractionStatus.SUCCESS.value, QualityStatus.GOOD.value, text_class, coverage)
    if e:
        code, msg = ErrorCode.PAGE_ERRORS.value, f"{e} page(s) could not be parsed"
    elif truncated:
        code, msg = ErrorCode.PAGE_LIMIT.value, "Page limit reached; remaining pages not parsed"
    else:
        code, msg = ErrorCode.PAGES_NEED_OCR.value, f"{s} page(s) are images without a text layer"
    return QualityResult(ExtractionStatus.PARTIAL_SUCCESS.value, QualityStatus.PARTIAL.value,
                         TextClass.TEXT_PARTIAL.value, coverage, code, msg)
