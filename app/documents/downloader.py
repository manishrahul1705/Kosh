"""Document download manager: safe, streaming, retrying, idempotency-friendly.

Design (Stage 2A reliability fix)
---------------------------------
* ``DocumentDownloader.fetch`` NEVER writes to a final/permanent filename.
  It streams the response into a *uniquely named* temporary file, hashing and
  size-limiting while streaming, validates the real content, and hands the
  caller a :class:`DownloadedFile`.
* The caller (``DocumentsService``) compares the SHA-256 with the existing
  versions and only then decides to publish the temp file as a new version or
  to discard it (UNCHANGED).  Because the temp name is unique and the final
  name is decided later, a previously stored file (e.g. a legacy v1 PDF) can
  never be hit by a rename collision (the Windows ``WinError 183`` bug).
* Transient failures (connection reset, timeout, HTTP 429/5xx) are retried at
  most 3 attempts with exponential backoff and ``Retry-After`` support.
  401/403/CAPTCHA/"access denied" are never retried and are reported as
  :class:`BlockedDownloadError`.
* Every redirect hop is re-validated with :func:`is_safe_url`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin,urlsplit

import httpx

from app.core.config import Settings
from app.documents.validator import validate_by_extension
from app.utils.dates import utcnow

logger = logging.getLogger("app.documents.downloader")

MAX_ATTEMPTS_CAP = 3
MAX_REDIRECTS = 5
MAX_PAGE_BYTES = 5 * 1024 * 1024  # HTML detail pages are small; cap them.
TEMP_PREFIX = ".tmp_"
TEMP_SUFFIX = ".part"
def urlsplit_path(url):
    p=urlsplit(url);return (p.hostname,p.path,p.query)
KNOWN_EXTENSIONS = {"pdf", "xlsx", "xls", "docx", "doc", "zip", "csv", "txt", "png", "jpg", "jpeg", "html"}

BLOCKED_INDICATORS = (
    "captcha",
    "verify you are human",
    "access denied",
    "403 forbidden",
    "robot check",
    "unusual traffic",
    "bot detection",
)


def looks_blocked(text: str) -> bool:
    """True if page text looks like CAPTCHA / human verification / access denial."""
    lowered = text.lower()
    return any(indicator in lowered for indicator in BLOCKED_INDICATORS)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class DownloadError(Exception):
    """Base exception for download failures."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class URLValidationError(DownloadError):
    """URL failed security validation."""


class FileTooLargeError(DownloadError):
    """Downloaded file exceeded size limit."""


class InvalidFileError(DownloadError):
    """Downloaded file failed validation (not a real document)."""


class HTTPError(DownloadError):
    """HTTP request failed (permanent: 404, 410, other 4xx ...)."""


class TransientDownloadError(HTTPError):
    """Temporary failure (connection reset, timeout, 429, 5xx) - retried, may be retried later."""

    def __init__(self, code: str, message: str, attempts: int = 1, retry_after: float | None = None):
        super().__init__(code, message)
        self.attempts = attempts
        self.retry_after = retry_after


class BlockedDownloadError(DownloadError):
    """401/403/CAPTCHA/human verification/access denied. Never retried, never bypassed."""


# ---------------------------------------------------------------------------
# URL safety / retry helpers
# ---------------------------------------------------------------------------
def is_safe_url(url: str, allowed_schemes: set[str] | None = None) -> bool:
    """Check if URL is safe to download.

    Only allows http:// and https://.
    Rejects localhost, private IPs, and other schemes.
    """
    if not url:
        return False

    allowed_schemes = allowed_schemes or {"http", "https"}

    if not url.startswith(("http://", "https://")):
        return False

    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)

        if parsed.scheme not in allowed_schemes:
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return False

        try:
            from ipaddress import ip_address, ip_network
            ip = ip_address(hostname)
            private_ranges = [
                ip_network("10.0.0.0/8"),
                ip_network("172.16.0.0/12"),
                ip_network("192.168.0.0/16"),
                ip_network("127.0.0.0/8"),
                ip_network("169.254.0.0/16"),
                ip_network("::1/128"),
            ]
            for net in private_ranges:
                if ip in net:
                    return False
        except ValueError:
            pass  # Not an IP literal, that's fine

        return True
    except Exception:
        return False


def should_retry(status_code: int) -> bool:
    """Determine if an HTTP status should trigger a retry."""
    return status_code in (429, 500, 502, 503, 504)


def calculate_backoff(attempt: int, base: float = 2.0, max_wait: float = 60.0) -> float:
    """Legacy helper: exponential backoff ``base ** attempt`` (kept for compatibility)."""
    wait = base ** attempt
    return min(wait, max_wait)


def compute_backoff(attempt: int, base: float, max_wait: float = 60.0) -> float:
    """Exponential backoff ``base * 2**attempt`` (attempt is 0-based). base=0 -> no wait."""
    return min(max(base, 0.0) * (2 ** attempt), max_wait)


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (delta-seconds or HTTP date) into seconds."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(int(value)))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is not None:
            seconds = (when - datetime.now(when.tzinfo)).total_seconds()
        else:
            seconds = (when - datetime.utcnow()).total_seconds()
        return max(0.0, seconds)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------
@dataclass
class DownloadedFile:
    """A validated file sitting in a unique temp location. Caller owns cleanup."""

    temp_path: Path
    sha256: str
    file_size: int
    url: str
    final_url: str
    http_status: int
    content_type: str
    content_disposition: str | None
    extension: str  # sniffed/validated extension, e.g. "pdf" ("" if unknown)
    downloaded_at: datetime = field(default_factory=utcnow)

    def cleanup(self) -> None:
        """Delete the temp file (idempotent)."""
        try:
            self.temp_path.unlink(missing_ok=True)
        except OSError as e:  # pragma: no cover - best effort
            logger.warning(f"Could not remove temp file {self.temp_path}: {e}")


@dataclass
class FetchResult:
    """Either a downloaded file or an HTML page (page mode only)."""

    file: DownloadedFile | None = None
    page_html: str | None = None
    final_url: str = ""
    http_status: int = 0
    content_type: str = ""


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------
class DocumentDownloader:
    """Safe streaming downloader with conservative retry and temp-file hygiene."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        url_policy=None,
    ):
        self.url_policy = url_policy
        self.settings = settings
        self.max_size_bytes = settings.max_document_size_mb * 1024 * 1024
        self.timeout = settings.document_request_timeout_seconds
        self.connect_timeout = settings.document_connect_timeout_seconds
        self.attempt_timeout = settings.document_download_timeout_seconds
        self.max_retries = settings.document_max_retries
        self.delay = settings.document_request_delay_seconds
        # Total attempts: retries+1, never more than 3 (conservative toward GeM).
        self.max_attempts = max(1, min(MAX_ATTEMPTS_CAP, self.max_retries + 1))
        self.backoff_base = settings.backoff_base_seconds
        self.max_retry_after = settings.max_retry_after_seconds
        self._transport = transport
        self._sleep = sleep or time.sleep

    # -- public API -------------------------------------------------------
    def fetch(
        self,
        url: str,
        temp_dir: Path,
        filename_hint: str | None = None,
        allow_page: bool = False,
    ) -> FetchResult:
        """Fetch ``url`` with retry. Streams files into a unique temp file in ``temp_dir``.

        allow_page=True : an HTML response is returned as ``page_html`` (discovery mode).
        allow_page=False: an HTML response is an error (blocked or invalid file).

        Raises URLValidationError, BlockedDownloadError, FileTooLargeError,
        InvalidFileError, HTTPError (permanent), TransientDownloadError
        (after all attempts).
        """
        if not is_safe_url(url):
            raise URLValidationError("UNSAFE_URL", f"URL failed security validation: {url}")

        if self.url_policy:
            self.url_policy.validate(url)
        temp_dir.mkdir(parents=True, exist_ok=True)

        last_error: TransientDownloadError | None = None
        for attempt in range(self.max_attempts):
            try:
                return self._attempt(url, temp_dir, filename_hint, allow_page)
            except TransientDownloadError as e:
                last_error = e
                if attempt + 1 >= self.max_attempts:
                    break
                wait = compute_backoff(attempt, self.backoff_base)
                if e.retry_after is not None:
                    wait = max(wait, min(e.retry_after, self.max_retry_after))
                logger.warning(
                    f"Transient failure fetching {url} ({e.code}: {e.message}); "
                    f"retrying in {wait:.1f}s (attempt {attempt + 1}/{self.max_attempts})"
                )
                self._sleep(wait)

        assert last_error is not None
        raise TransientDownloadError(
            last_error.code,
            f"{last_error.message} (failed after {self.max_attempts} transient attempt(s))",
            attempts=self.max_attempts,
            retry_after=last_error.retry_after,
        )

    def suggest_filename(self, downloaded: DownloadedFile, filename_hint: str | None = None) -> str:
        """Safe filename for a downloaded file (Content-Disposition > URL > hint > hash)."""
        name = self._determine_filename(downloaded.url, downloaded.content_disposition, filename_hint)
        suffix = Path(name).suffix.lstrip(".").lower()
        stem = Path(name).stem or "document"
        if downloaded.extension == "pdf" and suffix != "pdf":
            # The bytes are a real PDF; make the stored name say so.
            name = f"{stem}.pdf" if suffix in KNOWN_EXTENSIONS or not suffix else f"{name}.pdf"
        elif downloaded.extension and suffix not in KNOWN_EXTENSIONS:
            name = f"{stem}.{downloaded.extension}"
        return self._sanitize_filename(name)

    # -- internals --------------------------------------------------------
    def _attempt(
        self,
        url: str,
        temp_dir: Path,
        filename_hint: str | None,
        allow_page: bool,
    ) -> FetchResult:
        headers = {"User-Agent": self.settings.user_agent}
        client_kwargs: dict = {"timeout": httpx.Timeout(self.timeout, connect=min(self.timeout,self.connect_timeout)), "follow_redirects": False, "trust_env": False}
        deadline=time.monotonic()+self.attempt_timeout
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            with httpx.Client(**client_kwargs) as client:
                current = url
                from app.documents.reference_security import fulfilment_attachment
                attachment=fulfilment_attachment(url) if self.url_policy else None
                for _hop in range(MAX_REDIRECTS + 1):
                    self._check_deadline(deadline)
                    if self.url_policy:
                        self.url_policy.validate(current)
                    with client.stream("GET", current, headers=headers) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise HTTPError("BAD_REDIRECT", "Redirect without Location header")
                            nxt = urljoin(str(response.url), location)
                            if not is_safe_url(nxt):
                                raise URLValidationError(
                                    "UNSAFE_REDIRECT", f"Redirect target failed security validation: {nxt}"
                                )
                            if self.url_policy:
                                self.url_policy.validate(nxt)
                                from app.documents.catalogue import is_catalogue_url
                                if is_catalogue_url(url) and urlsplit_path(nxt)!=urlsplit_path(url):
                                    raise URLValidationError('UNSAFE_REFERENCE_REDIRECT','Catalogue redirect must retain the verified specification identity')
                                if attachment:
                                    redirected=fulfilment_attachment(nxt)
                                    if not redirected or redirected['bid']!=attachment['bid']:
                                        raise URLValidationError('UNSAFE_REFERENCE_REDIRECT','Attachment redirect must remain within the verified tender package')
                            current = nxt
                            continue
                        return self._handle_response(response, url, temp_dir, filename_hint, allow_page, deadline)
                raise HTTPError("TOO_MANY_REDIRECTS", f"More than {MAX_REDIRECTS} redirects")
        except httpx.UnsupportedProtocol as e:
            raise URLValidationError("UNSAFE_URL", str(e))
        except httpx.TimeoutException as e:
            raise TransientDownloadError("TIMEOUT", f"Request timeout ({type(e).__name__})")
        except httpx.TransportError as e:
            # ConnectError, ReadError, RemoteProtocolError, ... incl. WinError 10054 resets.
            detail = str(e) or type(e).__name__
            raise TransientDownloadError("CONNECTION_ERROR", f"Connection error: {detail}")
        except httpx.RequestError as e:
            raise HTTPError("REQUEST_ERROR", str(e) or type(e).__name__)

    def _handle_response(
        self,
        response: httpx.Response,
        url: str,
        temp_dir: Path,
        filename_hint: str | None,
        allow_page: bool,
        deadline: float | None = None,
    ) -> FetchResult:
        status = response.status_code
        final_url = str(response.url)

        if status in (401, 403):
            raise BlockedDownloadError(f"HTTP_{status}", f"HTTP {status} - access denied/blocked")
        if should_retry(status):
            raise TransientDownloadError(
                f"HTTP_{status}",
                f"HTTP {status} from server",
                retry_after=parse_retry_after(response.headers.get("retry-after")),
            )
        if status >= 400:
            raise HTTPError(str(status), f"HTTP {status}")
        if not 200 <= status < 300:
            raise HTTPError(str(status), f"Unexpected HTTP status {status}")

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        content_disposition = response.headers.get("content-disposition")

        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_size_bytes:
                    raise FileTooLargeError(
                        "FILE_TOO_LARGE",
                        f"File size {content_length} exceeds limit {self.max_size_bytes}",
                    )
            except ValueError:
                pass  # ignore invalid header

        chunks = response.iter_bytes(chunk_size=64 * 1024)
        first = b""
        for first in chunks:
            self._check_deadline(deadline)
            if first:
                break

        is_html_type = content_type in ("", "text/html", "application/xhtml+xml")
        looks_pdf = first.startswith(b"%PDF")
        treat_as_html = is_html_type and not looks_pdf

        catalogue_file=False
        if treat_as_html:
            body = first
            if len(body)>MAX_PAGE_BYTES:
                raise FileTooLargeError('PAGE_TOO_LARGE','HTML response exceeds bounded page size')
            for chunk in chunks:
                self._check_deadline(deadline)
                body += chunk
                if len(body) > MAX_PAGE_BYTES:
                    raise FileTooLargeError('PAGE_TOO_LARGE','HTML response exceeds bounded page size')
            text = body.decode(response.encoding or "utf-8", errors="replace")
            if looks_blocked(text):
                raise BlockedDownloadError(
                    "BLOCKED", "Page access blocked by human verification (CAPTCHA/access denied)"
                )
            if allow_page:
                return FetchResult(
                    page_html=text, final_url=final_url, http_status=status, content_type=content_type
                )
            from app.documents.catalogue import is_catalogue_url,catalogue_rows
            if self.url_policy and is_catalogue_url(url) and is_catalogue_url(final_url) and urlsplit_path(url)==urlsplit_path(final_url):
                from app.documents.formats import DocumentFormatError
                try:catalogue_rows(text)
                except DocumentFormatError as exc:raise InvalidFileError('UNSUPPORTED_CATALOGUE',str(exc)) from exc
                first=body;chunks=iter(());catalogue_file=True
            else:
                raise InvalidFileError("INVALID_FILE", "File validation failed: server returned an HTML page instead of a document")

        # ---- file mode: stream to a unique temp file -------------------
        fd, tmp_name = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX, dir=str(temp_dir))
        temp_path = Path(tmp_name)
        try:
            sha256 = hashlib.sha256()
            size = 0
            with os.fdopen(fd, "wb") as out:
                def _write(chunk: bytes) -> None:
                    nonlocal size
                    size += len(chunk)
                    if size > self.max_size_bytes:
                        raise FileTooLargeError(
                            "FILE_TOO_LARGE", f"Downloaded size exceeds limit {self.max_size_bytes}"
                        )
                    sha256.update(chunk)
                    out.write(chunk)

                if first:
                    _write(first)
                for chunk in chunks:
                    self._check_deadline(deadline)
                    if chunk:
                        _write(chunk)
                out.flush()
                os.fsync(out.fileno())

            if size == 0:
                raise TransientDownloadError("EMPTY_RESPONSE", "File download returned an empty response body")

            extension = self._choose_extension(url, content_disposition, filename_hint, content_type, first)
            if catalogue_file:extension='html'
            is_valid, error = validate_by_extension(temp_path, extension or None)
            if not is_valid:
                raise InvalidFileError("INVALID_FILE", f"File validation failed: {error}")
            from app.documents.formats import inspect_document, DocumentFormatError
            try:extension=inspect_document(temp_path, expected=extension, content_type=content_type)
            except DocumentFormatError as exc:
                raise InvalidFileError("INVALID_FILE", f"File validation failed: {exc}") from exc

            downloaded = DownloadedFile(
                temp_path=temp_path,
                sha256=sha256.hexdigest(),
                file_size=size,
                url=url,
                final_url=final_url,
                http_status=status,
                content_type=content_type,
                content_disposition=content_disposition,
                extension=extension,
                downloaded_at=utcnow(),
            )
            return FetchResult(
                file=downloaded, final_url=final_url, http_status=status, content_type=content_type
            )
        except BaseException:
            # Any failure (validation, size, network drop mid-stream, ...) -> no stale temp.
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover
                pass
            raise

    @staticmethod
    def _check_deadline(deadline):
        if deadline is not None and time.monotonic()>=deadline:
            raise TransientDownloadError('TIMEOUT','Download attempt exceeded total response budget')

    def _choose_extension(
        self,
        url: str,
        content_disposition: str | None,
        filename_hint: str | None,
        content_type: str,
        first_chunk: bytes,
    ) -> str:
        """Extension used for magic-byte validation."""
        if content_type == "application/pdf" or first_chunk.startswith(b"%PDF"):
            return "pdf"  # declared/sniffed PDF is validated as PDF (bytes must start with %PDF)
        name = self._determine_filename(url, content_disposition, filename_hint)
        return Path(name).suffix.lstrip(".").lower()

    def _determine_filename(
        self,
        url: str,
        content_disposition: str | None,
        filename_hint: str | None,
    ) -> str:
        """Determine safe filename from headers, URL or hint."""
        if content_disposition:
            from app.documents.classifier import extract_filename_from_header
            fn = extract_filename_from_header(content_disposition)
            if fn:
                return self._sanitize_filename(fn)

        from app.documents.classifier import extract_filename_from_url
        fn = extract_filename_from_url(url)
        if fn:
            return self._sanitize_filename(fn)

        if filename_hint:
            return self._sanitize_filename(filename_hint)

        hash_val = hashlib.sha256(url.encode()).hexdigest()[:8]
        return f"document_{hash_val}.bin"

    @staticmethod
    def _sanitize_filename(filename: str, max_length: int = 150) -> str:
        """Reduce to a safe, Windows-friendly basename (no separators/control chars)."""
        # Keep only the last path component, whatever separator was used.
        base = re.split(r"[/\\]", filename)[-1]
        safe = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base)
        safe = safe.strip(" .")
        if len(safe) > max_length:
            if "." in safe:
                name, ext = safe.rsplit(".", 1)
                safe = name[: max_length - len(ext) - 1] + "." + ext
            else:
                safe = safe[:max_length]
        return safe or "document.bin"

