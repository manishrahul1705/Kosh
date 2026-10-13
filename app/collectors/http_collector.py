"""Plain-HTTP transport for the public GeM listing (preferred method).

Flow (same requests the public page makes in a browser, no login):
1. GET the public listing page -> session cookie + public anti-CSRF token.
2. POST the listing JSON endpoint once per page, sequentially, with a delay.

Responsible-access rules implemented here:
* one request at a time (no concurrency), configurable delay between pages;
* conservative exponential backoff for 429/5xx/timeouts, honouring Retry-After;
* 403 / CAPTCHA / challenge pages raise BlockedError -> run stops, nothing
  is solved or evaded.
"""

from __future__ import annotations

import email.utils
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import (
    BlockedError,
    CollectorError,
    ListingTransport,
    RateLimitedError,
    SessionSetupError,
)
from app.collectors.debug import save_debug_snapshot
from app.collectors.gem_parser import (
    CSRF_COOKIE,
    CSRF_FIELD,
    build_listing_form,
    detect_block,
    extract_csrf_token,
)
from app.core.config import Settings
from app.core.logging import log_event

logger = logging.getLogger("app.collectors.http")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0.0, (dt - now).total_seconds())


def backoff_delay(attempt: int, base: float) -> float:
    """attempt 0 -> base, 1 -> 2*base, 2 -> 4*base (2s, 4s, 8s by default)."""
    return base * (2 ** attempt)


class HttpTransport(ListingTransport):
    name = "http"

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep
        self._token: str | None = None
        self._opened = False

    # -- session -------------------------------------------------------------
    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.settings.request_timeout_seconds),
                follow_redirects=True,
                headers={
                    "User-Agent": self.settings.user_agent,
                    "Accept-Language": "en-IN,en;q=0.9",
                },
            )
        return self._client

    def open(self) -> None:
        if self._opened:
            return
        self._refresh_session()
        self._opened = True

    def _refresh_session(self) -> None:
        url = self.settings.gem_bid_list_url
        resp = self._request("GET", url, headers={"Accept": "text/html,application/xhtml+xml"})
        html = resp.text
        token = extract_csrf_token(html)
        if not token:
            token = self._get_client().cookies.get(CSRF_COOKIE)
        if not token:
            reason = detect_block(html, resp.status_code)
            if reason:
                save_debug_snapshot(self.settings, "listing_blocked", html)
                raise BlockedError(reason, resp.status_code)
            save_debug_snapshot(self.settings, "listing_no_token", html)
            raise SessionSetupError("public listing page did not contain the expected session token")
        self._token = token
        log_event(logger, logging.INFO, "listing_session_ready", url=url)

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None
        self._opened = False

    # -- requests ------------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send with conservative retries. Raises Blocked/RateLimited/Collector errors."""
        client = self._get_client()
        max_retries = self.settings.max_retries
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                resp = client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt >= max_retries:
                    break
                delay = backoff_delay(attempt, self.settings.backoff_base_seconds)
                log_event(logger, logging.WARNING, "request_retry", method=method, url=url,
                          error=type(exc).__name__, attempt=attempt + 1, sleep_s=delay)
                self._sleep(delay)
                continue

            if resp.status_code == 403:
                save_debug_snapshot(self.settings, "http403", resp.text)
                raise BlockedError("HTTP 403 Forbidden (access denied by source)", 403)

            if resp.status_code in RETRYABLE_STATUS:
                if attempt >= max_retries:
                    if resp.status_code == 429:
                        raise RateLimitedError("HTTP 429 Too Many Requests persisted after retries")
                    raise CollectorError(f"HTTP {resp.status_code} persisted after {max_retries} retries")
                delay = backoff_delay(attempt, self.settings.backoff_base_seconds)
                retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                if retry_after is not None:
                    if retry_after > self.settings.max_retry_after_seconds:
                        raise RateLimitedError(
                            f"source asked to wait {retry_after:.0f}s (> MAX_RETRY_AFTER_SECONDS); stopping run"
                        )
                    delay = max(delay, retry_after)
                log_event(logger, logging.WARNING, "request_retry", method=method, url=url,
                          status=resp.status_code, attempt=attempt + 1, sleep_s=delay)
                self._sleep(delay)
                continue
            return resp
        raise CollectorError(f"network error after {max_retries} retries: {type(last_exc).__name__}: {last_exc}")

    def fetch_page(self, page: int) -> dict[str, Any]:
        self.open()
        refreshed = False
        while True:
            form = build_listing_form(page, self.settings.gem_sort)
            form[CSRF_FIELD] = self._token or ""
            resp = self._request(
                "POST",
                self.settings.resolved_data_url,
                data=form,
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.settings.gem_bid_list_url,
                },
            )
            if resp.status_code == 404:
                # The listing answers 404 for an empty result page.
                return {}
            text = resp.text
            stripped = text.lstrip()
            if stripped.startswith("{"):
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    save_debug_snapshot(self.settings, f"page{page}_badjson", text)
                    raise CollectorError(f"page {page}: invalid JSON ({exc})") from exc
                if isinstance(data, dict):
                    return data
                raise CollectorError(f"page {page}: JSON was not an object")

            reason = detect_block(text, resp.status_code)
            if reason:
                save_debug_snapshot(self.settings, f"page{page}_blocked", text)
                raise BlockedError(reason, resp.status_code)
            if resp.status_code >= 400:
                save_debug_snapshot(self.settings, f"page{page}_http{resp.status_code}", text)
                raise CollectorError(f"page {page}: HTTP {resp.status_code}")
            # Non-JSON 200: usually an expired anti-CSRF token. Re-load the
            # public page once (normal browser behaviour), then give up.
            if refreshed:
                save_debug_snapshot(self.settings, f"page{page}_nonjson", text)
                raise CollectorError(f"page {page}: non-JSON response after session refresh")
            log_event(logger, logging.WARNING, "session_refresh", page=page)
            refreshed = True
            self._sleep(self.settings.request_delay_seconds)
            self._refresh_session()
