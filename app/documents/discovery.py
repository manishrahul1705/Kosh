"""Document discovery: finding documents on tender detail pages."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.config import Settings
from app.database.models import Tender
from app.documents.downloader import (
    BlockedDownloadError,
    DocumentDownloader,
    DownloadedFile,
    DownloadError,
    TransientDownloadError,
    looks_blocked,
)
from app.schemas.documents import DocumentCandidate, DocumentType

logger = logging.getLogger("app.documents.discovery")


class DocumentDiscoveryError(Exception):
    """Error discovering documents."""
    pass


class BlockedByVerification(DocumentDiscoveryError):
    """Page access blocked by human verification."""
    pass


class DiscoveryTransientError(DocumentDiscoveryError):
    """Network/server trouble (reset, timeout, 429, 5xx) persisted through all attempts.

    This is NOT "the tender has no documents"; it must be reported as a failure.
    """

    def __init__(self, message: str, attempts: int = 1, code: str | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.code = code


class DiscoveryPermanentError(DocumentDiscoveryError):
    """Discovery failed for a non-transient reason (404, unsupported content, unsafe URL...)."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


# GeM serves reverse-auction (GEM/yyyy/R/n) documents from a different path than
# regular bids (confirmed: showbidDocument/{id} returns an empty body for RAs,
# showradocumentPdf/{id} returns the PDF).  For an RA these same-origin paths are
# tried first, then the stored URL.  Only these "not served here"
# outcomes trigger a fallback; blocks/CAPTCHA always stop immediately.
RA_DOCUMENT_PATHS = ("showradocumentPdf",)
_FALLBACK_CODES = {"EMPTY_RESPONSE", "404", "410"}


@dataclass
class DiscoveryResult:
    """Candidates plus any file already fetched during discovery (direct PDF).

    ``prefetched`` maps candidate source_url -> DownloadedFile (temp file), so the
    same PDF is not requested twice. Whoever does not consume an entry must call
    :meth:`cleanup` so no temp file is left behind.
    """

    candidates: list[DocumentCandidate] = field(default_factory=list)
    prefetched: dict[str, DownloadedFile] = field(default_factory=dict)

    def take_prefetched(self, url: str) -> DownloadedFile | None:
        return self.prefetched.pop(url, None)

    def cleanup(self) -> None:
        for dl in list(self.prefetched.values()):
            dl.cleanup()
        self.prefetched.clear()


class DocumentDiscovery:
    """Discover documents on GeM tender detail pages."""

    def __init__(self, settings: Settings, downloader: DocumentDownloader | None = None):
        self.settings = settings
        self.gem_source_origin = settings.source_origin
        self.downloader = downloader or DocumentDownloader(settings)

    def build_tender_detail_url(self, tender: Tender) -> str:
        """Build the GeM tender detail page URL from tender data."""
        if not tender.source_internal_id:
            raise ValueError(f"Tender {tender.id} has no source_internal_id (GeM b_id)")

        # GeM detail page URL format: {origin}/showbidDocument/{b_id}
        # This is constructed from the listing's source URL pattern
        return f"{self.gem_source_origin}/showbidDocument/{tender.source_internal_id}"

    def document_urls(self, tender: Tender) -> list[str]:
        """URLs to try for the tender's main document, in order.

        Regular bids: the stored URL only.  Reverse auctions: the RA document
        path first (where GeM actually serves them), then the stored URL as a
        fallback, so each RA costs one request instead of several empty ones.
        """
        stored = [tender.source_url] if tender.source_url else []
        if not (self._is_reverse_auction(tender) and tender.source_internal_id):
            return stored
        urls = [f"{self.gem_source_origin}/{path}/{tender.source_internal_id}" for path in RA_DOCUMENT_PATHS]
        return urls + [u for u in stored if u not in urls]

    @staticmethod
    def _is_reverse_auction(tender: Tender) -> bool:
        if (getattr(tender, "bid_type", None) or "").upper() == "RA":
            return True
        return "/R/" in (tender.bid_number or "").upper()

    def discover_documents(
        self,
        tender: Tender,
        page_html: str | None = None,
    ) -> list[DocumentCandidate]:
        """Backward-compatible wrapper: returns only the candidates.

        Any file prefetched for a direct PDF is discarded (temp file removed).
        Prefer :meth:`discover` which keeps the prefetched file for reuse.
        """
        result = self.discover(tender, page_html)
        result.cleanup()
        return result.candidates

    def discover(
        self,
        tender: Tender,
        page_html: str | None = None,
        temp_dir: Path | None = None,
    ) -> DiscoveryResult:
        """Discover all documents for a tender.

        If page_html is provided, use it (for testing).
        Otherwise fetch tender.source_url once (with conservative retry).  When
        that URL serves a PDF directly (GeM /showbidDocument/{id}), the PDF is
        streamed once into a temp file and returned in ``prefetched`` so the
        download step does not request it a second time.

        Raises:
            BlockedByVerification: CAPTCHA / human verification / 401 / 403
            DiscoveryTransientError: transient network/server failure after all attempts
            DiscoveryPermanentError: any other non-recoverable fetch problem
        """
        prefetched: dict[str, DownloadedFile] = {}
        main_url = tender.source_url if tender is not None else None

        if page_html is None:
            urls = self.document_urls(tender)
            if not urls:
                logger.warning(f"Tender {tender.id} has no source_url, cannot discover documents")
                return DiscoveryResult()

            for i, url in enumerate(urls):
                try:
                    page_html, fetched = self._fetch_tender_page(url, tender, temp_dir)
                except (DiscoveryTransientError, DiscoveryPermanentError) as e:
                    if i + 1 < len(urls) and e.code in _FALLBACK_CODES:
                        logger.info(f"Tender {tender.id}: {e.code} at {url}; trying {urls[i + 1]}")
                        continue
                    raise
                main_url = url
                if fetched is not None:
                    prefetched[url] = fetched
                break

        try:
            candidates = self._extract_document_candidates(page_html, tender, main_url=main_url)
        except BaseException:
            for dl in prefetched.values():
                dl.cleanup()
            raise
        return DiscoveryResult(candidates=candidates, prefetched=prefetched)

    def _fetch_tender_page(
        self,
        source_url: str,
        tender: Tender,
        temp_dir: Path | None = None,
    ) -> tuple[str, DownloadedFile | None]:
        """Fetch the tender detail URL once.

        Returns (html, prefetched_file):
          * HTML page      -> (page_html, None)
          * direct PDF     -> (synthetic marker html, DownloadedFile in a unique temp file)

        Raises BlockedByVerification / DiscoveryTransientError / DiscoveryPermanentError.
        Never returns "nothing" for a failure: failures are never "0 documents".
        """
        temp_dir = temp_dir or (self.settings.resolved_document_storage_path / "_incoming")
        try:
            result = self.downloader.fetch(source_url, temp_dir, allow_page=True)
        except BlockedDownloadError as e:
            raise BlockedByVerification(f"{e.message} [{e.code}]") from e
        except TransientDownloadError as e:
            raise DiscoveryTransientError(
                f"Document discovery failed after {e.attempts} transient attempt(s): "
                f"{e.message.split(' (failed after')[0]}",
                attempts=e.attempts,
                code=e.code,
            ) from e
        except DownloadError as e:
            raise DiscoveryPermanentError(f"Document discovery failed: {e.code}: {e.message}", code=e.code) from e

        if result.file is not None:
            dl = result.file
            if dl.extension == "pdf":
                logger.info(f"Tender {tender.id}: Direct PDF detected at {source_url}")
                return self._create_direct_pdf_marker(source_url, tender), dl
            dl.cleanup()
            raise DiscoveryPermanentError(
                f"Unexpected non-PDF content type at {source_url}: {result.content_type or 'unknown'}"
            )

        return result.page_html or "", None

    @staticmethod
    def _create_direct_pdf_marker(source_url: str, tender: Tender) -> str:
        """Create synthetic HTML marker for direct PDF response.
        
        This allows the link extraction logic to work unchanged,
        while signaling that a direct PDF was detected.
        """
        bid_number = tender.bid_number or "Tender"
        return f'''
        <html>
        <head><title>Direct PDF: {bid_number}</title></head>
        <body>
        <h1>Main Bid Document</h1>
        <p>Direct PDF detected at tender detail URL</p>
        <a href="{source_url}" title="Main Bid">
        Main Bid PDF
        </a>
        </body>
        </html>
        '''

    def _extract_document_candidates(
        self,
        page_html: str,
        tender: Tender,
        main_url: str | None = None,
    ) -> list[DocumentCandidate]:
        """Extract document candidates from tender detail page HTML.

        Looks for download links, classifies them by type.
        Detects direct PDF responses and marks as MAIN_BID.
        """
        candidates = []

        # Check for CAPTCHA/verification blocks
        if self._is_blocked(page_html):
            raise BlockedByVerification(
                "Page access blocked by human verification (CAPTCHA/403)"
            )

        # Check if this is the synthetic PDF marker
        is_direct_pdf = "Direct PDF detected at tender detail URL" in page_html

        # Extract all links that look like documents
        # Pattern: href="..." or data-url="..." with document indicators
        link_pattern = r'(?:href|src|data-url|data-download)=["\']([^"\']+)["\']'
        links = re.findall(link_pattern, page_html, re.IGNORECASE)

        # Also look for JavaScript download functions
        # e.g., downloadFile('/path/to/file.pdf')
        js_pattern = r'(?:downloadFile|download|getFile)\(["\']([^"\']+)["\']\)'
        js_links = re.findall(js_pattern, page_html)
        links.extend(js_links)

        # Extract text near links to get display names
        # This is a simplified approach
        # In a real implementation, would parse DOM properly

        document_labels = self._extract_document_labels(page_html)

        # Build candidates from links and labels
        processed_urls = set()

        for url in links:
            url = url.strip()
            if not url or url in processed_urls:
                continue

            # Normalize URL
            if url.startswith("/"):
                url = self.gem_source_origin + url
            elif not url.startswith(("http://", "https://")):
                # Relative URL - make absolute
                url = self.gem_source_origin + "/" + url

            processed_urls.add(url)

            # Find corresponding label
            display_name = self._find_label_for_url(url, page_html, document_labels)

            # Extract filename from URL
            filename = url.split("/")[-1].split("?")[0]

            if filename and filename != "":
                # Determine document type
                doc_type = DocumentType.UNKNOWN
                
                # Check if this is the direct PDF URL
                if main_url is None and tender is not None:
                    main_url = tender.source_url
                is_main_bid_url = bool(main_url) and url == main_url
                if is_direct_pdf and is_main_bid_url:
                    # Direct PDF from tender detail page = MAIN_BID
                    doc_type = DocumentType.MAIN_BID
                    if not display_name:
                        display_name = "Main Bid"
                    if not filename or "." not in filename:  # bare numeric ID in URL
                        filename = f"main_bid_{tender.id}.pdf"

                candidate = DocumentCandidate(
                    source_url=url,
                    document_type=doc_type,
                    display_name=display_name,
                    original_filename=filename if "." in filename else None,
                    document_key=self._generate_document_key(display_name, filename),
                )
                candidates.append(candidate)

        return candidates

    @staticmethod
    def _is_blocked(page_html: str) -> bool:
        """Check if page is blocked by CAPTCHA or human verification."""
        return looks_blocked(page_html)

    @staticmethod
    def _extract_document_labels(html: str) -> list[str]:
        """Extract document type labels from HTML.

        Looks for common patterns like "Buyer Added ATC", "BOQ", etc.
        """
        labels = []

        # Common document type patterns in GeM
        patterns = [
            r"Main.*?Bid",
            r"Buyer\s+Added\s+ATC",
            r"ATC",
            r"Specification",
            r"BOQ",
            r"Bill\s+of\s+Quantities",
            r"Scope\s+of\s+Work",
            r"Corrigendum",
            r"Annexure",
            r"Technical.*?Document",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            labels.extend(matches)

        return labels

    @staticmethod
    def _find_label_for_url(url: str, html: str, labels: list[str]) -> str | None:
        """Find display name/label for a URL from surrounding HTML."""
        # Try to find label near the URL in HTML
        url_escaped = re.escape(url)
        # Look in a window around the URL
        pattern = rf".{{0,200}}{url_escaped}.{{0,200}}"
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)

        if match:
            context = match.group(0)
            # Look for labels in context
            for label in labels:
                if label.lower() in context.lower():
                    return label

        # Fall back to filename-based label
        filename = url.split("/")[-1].split("?")[0]
        return filename if filename and "." in filename else None

    @staticmethod
    def _generate_document_key(display_name: str | None, filename: str | None) -> str:
        """Generate unique document key."""
        import hashlib

        key_source = f"{display_name or ''}-{filename or ''}".lower().strip()
        if key_source:
            # Use hash to ensure uniqueness
            hash_suffix = hashlib.md5(key_source.encode()).hexdigest()[:8]
            # Sanitize for use as identifier
            import re
            safe_name = re.sub(r"[^a-z0-9_-]", "_", key_source[:32])
            return f"{safe_name}_{hash_suffix}"

        return "unknown_document"
