"""Playwright transport — used only when plain HTTP cannot open the listing.

It loads the public listing in a real headless browser (so any JavaScript the
page needs runs normally) and then issues the *same* listing request the page
itself makes, from inside the page. No CAPTCHA solving, no stealth plugins, no
fingerprint spoofing: if a challenge appears, BlockedError stops the run.

Install once:  pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import logging
from typing import Any

from app.collectors.base import BlockedError, CollectorError, ListingTransport, SessionSetupError
from app.collectors.debug import save_debug_snapshot
from app.collectors.gem_parser import CSRF_FIELD, build_listing_form, detect_block, extract_csrf_token
from app.core.config import Settings
from app.core.logging import log_event

logger = logging.getLogger("app.collectors.browser")

_FETCH_JS = """
async ({url, form}) => {
  const body = new URLSearchParams(form);
  const r = await fetch(url, {
    method: 'POST',
    body,
    credentials: 'same-origin',
    headers: {'X-Requested-With': 'XMLHttpRequest',
              'Accept': 'application/json, text/javascript, */*; q=0.01'}
  });
  return {status: r.status, text: await r.text()};
}
"""


class BrowserTransport(ListingTransport):
    name = "browser"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pw = None
        self._browser = None
        self._page = None
        self._token: str | None = None

    def open(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on env
            raise CollectorError(
                "browser mode needs Playwright: pip install playwright && python -m playwright install chromium"
            ) from exc
        timeout_ms = int(self.settings.request_timeout_seconds * 1000)
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            context = self._browser.new_context(user_agent=self.settings.user_agent)
            self._page = context.new_page()
            resp = self._page.goto(self.settings.gem_bid_list_url, wait_until="networkidle", timeout=timeout_ms)
            html = self._page.content()
        except Exception as exc:
            self.close()
            raise CollectorError(f"browser could not load listing: {type(exc).__name__}: {exc}") from exc

        status = resp.status if resp is not None else None
        self._token = extract_csrf_token(html)
        if not self._token:
            for cookie in self._page.context.cookies():
                if cookie.get("name") == "csrf_gem_cookie":
                    self._token = cookie.get("value")
        if status == 403 or not self._token:
            reason = detect_block(html, status)
            if reason:
                save_debug_snapshot(self.settings, "browser_listing_blocked", html)
                self.close()
                raise BlockedError(reason, status)
            save_debug_snapshot(self.settings, "browser_listing_no_token", html)
            self.close()
            raise SessionSetupError("listing loaded in browser but no session token was found")
        log_event(logger, logging.INFO, "browser_session_ready", url=self.settings.gem_bid_list_url)

    def fetch_page(self, page: int) -> dict[str, Any]:
        self.open()
        form = build_listing_form(page, self.settings.gem_sort)
        form[CSRF_FIELD] = self._token or ""
        try:
            res = self._page.evaluate(_FETCH_JS, {"url": self.settings.resolved_data_url, "form": form})
        except Exception as exc:
            raise CollectorError(f"browser fetch failed on page {page}: {exc}") from exc
        status, text = res.get("status"), res.get("text") or ""
        if status == 404:
            return {}
        stripped = text.lstrip()
        if stripped.startswith("{"):
            import json

            try:
                data = json.loads(stripped)
            except ValueError as exc:
                raise CollectorError(f"page {page}: invalid JSON") from exc
            if isinstance(data, dict):
                return data
        reason = detect_block(text, status)
        if reason:
            save_debug_snapshot(self.settings, f"browser_page{page}_blocked", text)
            raise BlockedError(reason, status)
        save_debug_snapshot(self.settings, f"browser_page{page}_unexpected", text)
        raise CollectorError(f"page {page}: unexpected response (HTTP {status})")

    def close(self) -> None:
        for obj, meth in ((self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, meth)()
                except Exception:  # pragma: no cover
                    pass
        self._pw = self._browser = self._page = None
