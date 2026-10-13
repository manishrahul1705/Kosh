"""Offline transport that replays saved listing pages (tests / demos / CI).

Directory layout: ``page_1.json``, ``page_2.json``, ... (raw listing JSON as
returned by the source). A ``page_N.html`` file is treated as a non-JSON
response (e.g. a saved CAPTCHA page) and goes through the same block
detection as live traffic. A missing page means "no more results".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.collectors.base import BlockedError, CollectorError, ListingTransport
from app.collectors.gem_parser import detect_block


class FixtureTransport(ListingTransport):
    name = "fixture"

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.requests: list[int] = []

    def open(self) -> None:
        if not self.directory.is_dir():
            raise CollectorError(f"fixture directory not found: {self.directory}")

    def fetch_page(self, page: int) -> dict[str, Any]:
        self.requests.append(page)
        json_path = self.directory / f"page_{page}.json"
        html_path = self.directory / f"page_{page}.html"
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise CollectorError(f"fixture {json_path.name} is not a JSON object")
            return data
        if html_path.exists():
            text = html_path.read_text(encoding="utf-8")
            reason = detect_block(text)
            if reason:
                raise BlockedError(reason)
            raise CollectorError(f"page {page}: non-JSON response")
        return {}
