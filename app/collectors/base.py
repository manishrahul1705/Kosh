"""Collector contracts shared by all transports.

Everything outside ``app/collectors`` only sees ``CollectorResult`` and
``TenderRecord`` objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.schemas.tender import TenderRecord


class CollectorError(Exception):
    """A transport-level failure that ends pagination for this run."""


class BlockedError(CollectorError):
    """The source presented CAPTCHA / human verification / access denial.

    Never retried with a different identity, never solved: the run stops.
    """

    def __init__(self, reason: str, http_status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


class RateLimitedError(CollectorError):
    """HTTP 429 persisted after conservative, Retry-After-respecting retries."""


class SessionSetupError(CollectorError):
    """Could not establish the public listing session (e.g. token missing)."""


@dataclass
class ItemFailure:
    page: int
    index: int
    reason: str
    hint: str | None = None  # e.g. raw bid number, truncated

    def as_dict(self) -> dict[str, Any]:
        return {"page": self.page, "index": self.index, "reason": self.reason, "hint": self.hint}


@dataclass
class CollectorResult:
    records: list[TenderRecord] = field(default_factory=list)
    failures: list[ItemFailure] = field(default_factory=list)
    pages_checked: int = 0
    reported_total: int | None = None
    duplicates_skipped: int = 0
    truncated: bool = False  # stopped at MAX_PAGES_PER_RUN
    blocked: bool = False
    block_reason: str | None = None
    error: str | None = None
    collector_name: str = ""


class ListingTransport(ABC):
    """Fetches raw listing pages. One implementation per access method."""

    name: str = "transport"

    @abstractmethod
    def open(self) -> None:
        """Prepare the session (e.g. load the public listing page)."""

    @abstractmethod
    def fetch_page(self, page: int) -> dict[str, Any]:
        """Return the raw JSON payload for 1-based ``page``.

        An empty result page may be returned as ``{}``. Raise ``BlockedError``
        on CAPTCHA/verification, ``CollectorError`` for other hard failures.
        """

    def close(self) -> None:  # pragma: no cover - default no-op
        return None

    def __enter__(self) -> "ListingTransport":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class Collector(ABC):
    name: str = "collector"

    @abstractmethod
    def discover_live_tenders(self) -> CollectorResult:
        """Collect currently-live tenders across all listing pages."""
