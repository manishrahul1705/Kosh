"""GeM listing collector: pagination + parsing on top of a transport."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.collectors.base import (
    BlockedError,
    Collector,
    CollectorError,
    CollectorResult,
    ItemFailure,
    ListingTransport,
    SessionSetupError,
)
from app.collectors.debug import save_debug_snapshot
from app.collectors.gem_parser import PayloadShapeError, parse_listing_page
from app.core.config import Settings
from app.core.constants import BLOCKED_EVENT, CollectorMode, TenderStatus
from app.core.logging import log_event

logger = logging.getLogger("app.collectors.gem")


@dataclass
class PaginationLimits:
    max_pages: int = 100
    delay_seconds: float = 2.0


class GemListingCollector(Collector):
    """Walks the live (ongoing) listing page by page until exhausted."""

    def __init__(
        self,
        transport: ListingTransport,
        *,
        source_origin: str,
        limits: PaginationLimits,
        timestamp_zone: str = "UTC",
        settings: Settings | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.source_origin = source_origin
        self.limits = limits
        self.timestamp_zone = timestamp_zone
        self.settings = settings
        self._sleep = sleep
        self.name = f"gem:{transport.name}"

    def discover_live_tenders(self) -> CollectorResult:
        result = CollectorResult(collector_name=self.name)
        seen: set[str] = set()
        page_size: int | None = None
        try:
            self.transport.open()
            for page in range(1, self.limits.max_pages + 1):
                if page > 1 and self.limits.delay_seconds > 0:
                    self._sleep(self.limits.delay_seconds)
                payload = self.transport.fetch_page(page)
                result.pages_checked += 1
                try:
                    records, failures, doc_count, total = parse_listing_page(
                        payload,
                        page=page,
                        source_origin=self.source_origin,
                        timestamp_zone=self.timestamp_zone,
                        status=TenderStatus.ONGOING,
                    )
                except PayloadShapeError as exc:
                    save_debug_snapshot(self.settings, f"page{page}_shape", repr(payload)[:200000])
                    result.failures.append(ItemFailure(page, -1, f"unparseable page: {exc}"))
                    result.error = f"page {page}: {exc}"
                    log_event(logger, logging.ERROR, "page_unparseable", page=page, error=str(exc))
                    break

                if total is not None and result.reported_total is None:
                    result.reported_total = total
                for f in failures:
                    log_event(logger, logging.WARNING, "item_failed", page=f.page, index=f.index,
                              bid=f.hint, reason=f.reason)
                result.failures.extend(failures)
                for rec in records:
                    # Listing can shift while paginating; keep first sighting.
                    if rec.bid_number in seen:
                        result.duplicates_skipped += 1
                        continue
                    seen.add(rec.bid_number)
                    result.records.append(rec)
                log_event(logger, logging.INFO, "page_processed", page=page, bids=len(records),
                          failed=len(failures), total_reported=total)

                if doc_count == 0:
                    break
                if page_size is None:
                    page_size = doc_count
                if doc_count < page_size:
                    break
                if result.reported_total is not None and page * page_size >= result.reported_total:
                    break
            else:
                result.truncated = True
                log_event(logger, logging.WARNING, "max_pages_reached", max_pages=self.limits.max_pages,
                          total_reported=result.reported_total)
        except BlockedError as exc:
            result.blocked = True
            result.block_reason = exc.reason
            log_event(logger, logging.ERROR, BLOCKED_EVENT, reason=exc.reason,
                      pages_checked=result.pages_checked)
        except CollectorError as exc:
            result.error = str(exc)
            log_event(logger, logging.ERROR, "collector_error", error=str(exc),
                      pages_checked=result.pages_checked)
        finally:
            try:
                self.transport.close()
            except Exception:  # pragma: no cover
                logger.debug("transport close failed", exc_info=True)
        return result


class AutoCollector(Collector):
    """HTTP first; browser only if the HTTP session cannot be established.

    A *block* is never retried through the browser — that would be
    circumvention. Only a missing public token (page structure needs JS)
    triggers the fallback.
    """

    def __init__(self, http_collector: GemListingCollector, browser_factory: Callable[[], GemListingCollector]):
        self.http_collector = http_collector
        self.browser_factory = browser_factory
        self.name = "gem:auto"

    def discover_live_tenders(self) -> CollectorResult:
        transport = self.http_collector.transport
        try:
            transport.open()
        except SessionSetupError as exc:
            transport.close()
            log_event(logger, logging.WARNING, "http_session_unavailable_fallback_browser", reason=str(exc))
            return self.browser_factory().discover_live_tenders()
        except BlockedError as exc:
            transport.close()
            log_event(logger, logging.ERROR, BLOCKED_EVENT, reason=exc.reason, pages_checked=0)
            return CollectorResult(collector_name=self.name, blocked=True, block_reason=exc.reason)
        except CollectorError as exc:
            transport.close()
            log_event(logger, logging.ERROR, "collector_error", error=str(exc), pages_checked=0)
            return CollectorResult(collector_name=self.name, error=str(exc))
        # open() is idempotent; the collector reuses the established session.
        return self.http_collector.discover_live_tenders()


def build_collector(settings: Settings) -> Collector:
    """Factory used by the discovery service."""
    from app.collectors.browser_collector import BrowserTransport
    from app.collectors.fixture_collector import FixtureTransport
    from app.collectors.http_collector import HttpTransport

    limits = PaginationLimits(max_pages=settings.max_pages_per_run, delay_seconds=settings.request_delay_seconds)
    common = dict(
        source_origin=settings.source_origin,
        limits=limits,
        timestamp_zone=settings.gem_api_timestamp_zone,
        settings=settings,
    )
    mode = settings.collector_mode
    if mode == CollectorMode.FIXTURE:
        fixture_limits = PaginationLimits(max_pages=settings.max_pages_per_run, delay_seconds=0)
        return GemListingCollector(
            FixtureTransport(settings.resolve_path(settings.fixture_dir)),
            **{**common, "limits": fixture_limits},
        )
    if mode == CollectorMode.HTTP:
        return GemListingCollector(HttpTransport(settings), **common)
    if mode == CollectorMode.BROWSER:
        return GemListingCollector(BrowserTransport(settings), **common)
    return AutoCollector(
        GemListingCollector(HttpTransport(settings), **common),
        lambda: GemListingCollector(BrowserTransport(settings), **common),
    )
