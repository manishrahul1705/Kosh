"""Document type classification.

Deterministic classification based on filename and display name patterns.
Matches case-insensitively and tolerates whitespace variations.
"""

from __future__ import annotations

import re
from typing import Optional

from app.schemas.documents import DocumentType


def normalize_text(text: str | None) -> str:
    """Normalize text for classification: lowercase, compress whitespace."""
    if not text:
        return ""
    return " ".join(text.lower().split())


def classify_document(
    display_name: str | None,
    filename: str | None,
) -> DocumentType:
    """Classify a document based on display name and filename.
    
    Uses deterministic keyword matching. Falls back to UNKNOWN if uncertain.
    """
    display_norm = normalize_text(display_name)
    filename_norm = normalize_text(filename)
    combined = f"{display_norm} {filename_norm}"

    # Main Bid - primary document
    if any(p in combined for p in ["main bid", "bid document", "rfq", "rfq document"]):
        if not any(p in combined for p in ["corrig", "amend"]):
            return DocumentType.MAIN_BID

    # ATC (Addendum/Additional Terms & Conditions)
    if any(p in combined for p in ["atc", "additional terms", "addendum", "buyer added"]):
        if "corrig" not in combined:
            return DocumentType.ATC

    # Specification
    if any(p in combined for p in ["specification", "technical spec", "specs", "requirement"]):
        if "technical document" not in combined or "technical specification" in combined:
            return DocumentType.SPECIFICATION

    # BOQ (Bill of Quantities)
    if any(p in combined for p in ["boq", "bill of quantities", "bill of quantity"]):
        return DocumentType.BOQ

    # Scope of Work
    if any(p in combined for p in ["scope of work", "scope", "sow", "work statement"]):
        if "specification" not in combined:
            return DocumentType.SCOPE_OF_WORK

    # Corrigendum
    if any(p in combined for p in ["corrigendum", "corrigenda", "amendment", "amended", "corrigendums"]):
        return DocumentType.CORRIGENDUM

    # Annexure
    if any(p in combined for p in ["annexure", "annex", "appendix", "schedule"]):
        if "corrig" not in combined:
            return DocumentType.ANNEXURE

    # Drawing
    if any(p in combined for p in ["drawing", "blueprint", "cad", "schematic", "diagram"]):
        if "technical" not in combined:
            return DocumentType.DRAWING

    # Technical Document (catch-all for technical)
    if any(p in combined for p in ["technical", "test report", "certificate", "standards"]):
        return DocumentType.TECHNICAL_DOCUMENT

    # File extension-based hints (secondary)
    if filename_norm:
        if filename_norm.endswith(".pdf") and "bid" in display_norm:
            return DocumentType.MAIN_BID
        if filename_norm.endswith((".xlsx", ".xls", ".csv")):
            if "boq" in display_norm or "bill" in display_norm:
                return DocumentType.BOQ
            if "quantity" in display_norm:
                return DocumentType.BOQ

    # If we get here, it's unknown
    return DocumentType.UNKNOWN


def extract_filename_from_url(url: str) -> str | None:
    """Extract filename from URL, handling common patterns."""
    if not url:
        return None

    # Remove query string
    path = url.split("?")[0]
    # Get last component
    filename = path.rstrip("/").split("/")[-1]

    return filename if filename and "." in filename else None


def extract_filename_from_header(content_disposition: str | None) -> str | None:
    """Extract filename from Content-Disposition header.
    
    Example: attachment; filename="document.pdf"
    """
    if not content_disposition:
        return None

    # Look for filename*= (RFC 5987) first, then filename=
    for pattern in [r'filename\*=([^;\n]+)', r'filename=([^;\n]+)']:
        match = re.search(pattern, content_disposition, re.IGNORECASE)
        if match:
            fn = match.group(1).strip().strip('"\'')
            return fn if fn else None

    return None
