"""Reverse-auction (GEM/yyyy/R/n) document discovery falls back to the RA document path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.documents.discovery import (
    BlockedByVerification,
    DiscoveryTransientError,
    DocumentDiscovery,
)
from app.documents.downloader import (
    BlockedDownloadError,
    DownloadedFile,
    FetchResult,
    HTTPError,
    TransientDownloadError,
)
from app.schemas.documents import DocumentType

ORIGIN = "https://bidplus.gem.gov.in"


class FakeDownloader:
    def __init__(self, responses):
        self.responses = responses        # url -> FetchResult | Exception
        self.calls: list[str] = []

    def fetch(self, url, temp_dir, filename_hint=None, allow_page=False):
        self.calls.append(url)
        r = self.responses.get(url, HTTPError("404", "HTTP 404"))
        if isinstance(r, Exception):
            raise r
        return r


def _pdf(url, tmp_path: Path) -> FetchResult:
    p = tmp_path / "f.pdf"
    p.write_bytes(b"%PDF-1.4\n%%EOF")
    f = DownloadedFile(temp_path=p, sha256="x", file_size=14, url=url, final_url=url, http_status=200,
                       content_type="application/pdf", content_disposition=None, extension="pdf")
    return FetchResult(file=f, final_url=url, http_status=200, content_type="application/pdf")


def _tender(bid, internal_id="9994045"):
    return SimpleNamespace(id=1, bid_number=bid, bid_type="RA" if "/R/" in bid else "BID",
                           source_internal_id=internal_id,
                           source_url=f"{ORIGIN}/showbidDocument/{internal_id}")


def _discovery(responses):
    d = DocumentDiscovery(SimpleNamespace(source_origin=ORIGIN), downloader=FakeDownloader(responses))
    return d, d.downloader


EMPTY = TransientDownloadError("EMPTY_RESPONSE", "File download returned an empty response body", attempts=3)


STORED = f"{ORIGIN}/showbidDocument/9994045"
RA_URL = f"{ORIGIN}/showradocumentPdf/9994045"


def test_ra_goes_straight_to_ra_document(tmp_path):
    d, dl = _discovery({STORED: EMPTY, RA_URL: _pdf(RA_URL, tmp_path)})
    result = d.discover(_tender("GEM/2026/R/747705"), temp_dir=tmp_path)
    assert dl.calls == [RA_URL]                       # one request, no wasted empty fetches
    [c] = result.candidates
    assert c.source_url == RA_URL and c.document_type == DocumentType.MAIN_BID
    assert result.take_prefetched(RA_URL) is not None


def test_ra_falls_back_to_stored_url(tmp_path):
    d, dl = _discovery({RA_URL: EMPTY, STORED: _pdf(STORED, tmp_path)})
    [c] = d.discover(_tender("GEM/2026/R/747705"), temp_dir=tmp_path).candidates
    assert c.source_url == STORED and dl.calls == [RA_URL, STORED]


def test_ra_404_also_falls_back(tmp_path):
    d, dl = _discovery({STORED: _pdf(STORED, tmp_path)})          # RA path -> 404
    assert [c.source_url for c in d.discover(_tender("GEM/2026/R/747705"), temp_dir=tmp_path).candidates] == [STORED]


def test_regular_bid_never_tries_ra_path(tmp_path):
    d, dl = _discovery({STORED: EMPTY})
    with pytest.raises(DiscoveryTransientError):
        d.discover(_tender("GEM/2026/B/8121278"), temp_dir=tmp_path)
    assert dl.calls == [STORED]


def test_block_is_never_retried_on_another_url(tmp_path):
    d, dl = _discovery({RA_URL: BlockedDownloadError("HTTP_403", "blocked")})
    with pytest.raises(BlockedByVerification):
        d.discover(_tender("GEM/2026/R/747705"), temp_dir=tmp_path)
    assert len(dl.calls) == 1


def test_ra_all_urls_empty_reports_failure(tmp_path):
    d, dl = _discovery({STORED: EMPTY, RA_URL: EMPTY})
    with pytest.raises(DiscoveryTransientError) as e:
        d.discover(_tender("GEM/2026/R/747705"), temp_dir=tmp_path)
    assert e.value.code == "EMPTY_RESPONSE" and len(dl.calls) == 2
