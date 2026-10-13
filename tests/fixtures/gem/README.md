# GeM fixtures

Synthetic, sanitized data in the **exact JSON shape** returned by the public
`/all-bids-data` listing endpoint (shape taken from a real public response:
single-element lists, `response.response.{numFound,docs}`). Bid numbers,
ids and buyers are fictional. No cookies/tokens from a real session are stored
(the token in `listing_shell.html` is a made-up hex string).

| Directory | Purpose |
|---|---|
| `default/` | 13 bids over 2 pages (10 + 3) — demo / `COLLECTOR_MODE=fixture` |
| `mock_abc/initial` | Tenders A, B, C (mock test runs #1 and #2) |
| `mock_abc/b_closing_changed` | Same, Tender B closing 2026-10-10 15:00 IST -> 2026-10-12 18:00 IST |
| `malformed/` | 3 valid + 2 malformed docs (failed-item handling) |
| `blocked/` | page 1 OK, page 2 is a CAPTCHA page (block handling) |
