"""Shared HTTP plumbing for HTTP-based providers (httpx; no vendor SDK)."""

from __future__ import annotations

import json
import logging
from urllib.parse import urlsplit

import httpx

from app.ai.providers.base import (
    ProviderConfigError,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    classify_http_status,
    parse_retry_after,
)
from app.ai.redact import redact

# httpx/httpcore DEBUG output can include request headers (credentials). Never below WARNING.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def validate_base_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ProviderConfigError("AI_BASE_URL must be an absolute http(s) URL")
    return url.rstrip("/")


def validate_key(key: str) -> str:
    """Keys travel in an HTTP header: printable ASCII only (no whitespace / control chars)."""
    key = (key or "").strip()
    if key and (not key.isascii() or not key.isprintable() or any(c.isspace() for c in key)):
        raise ProviderConfigError("AI_API_KEY contains characters that are not allowed in an HTTP header")
    return key


def post_json(client: httpx.Client, url: str, *, headers: dict, body: dict, timeout: float,
              secret: str) -> dict:
    """POST JSON, return parsed JSON. Raises classified ProviderError (messages redacted).

    Credentials travel in headers only, never in the URL, so URLs are safe to log.
    """
    try:
        resp = client.post(url, headers=headers, json=body, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderTimeout(f"timeout after {timeout}s ({type(exc).__name__})") from None
    except (httpx.UnsupportedProtocol, httpx.InvalidURL, httpx.LocalProtocolError, UnicodeError, ValueError) as exc:
        # bad base URL / header value: configuration, never retried
        raise ProviderConfigError(f"request could not be built ({type(exc).__name__})") from None
    except httpx.TransportError as exc:
        raise ProviderUnavailable(redact(f"network error: {type(exc).__name__}: {exc}", secret)) from None
    if resp.status_code >= 400:
        raise classify_http_status(resp.status_code, _error_message(resp, secret),
                                   parse_retry_after(resp.headers.get("retry-after")))
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        raise ProviderUnavailable(f"HTTP {resp.status_code}: provider returned non-JSON body") from None
    if not isinstance(data, dict):
        raise ProviderUnavailable("provider returned an unexpected JSON shape")
    return data


def _error_message(resp: httpx.Response, secret: str) -> str:
    try:
        data = resp.json()
        err = data.get("error") if isinstance(data, dict) else None
        msg = err.get("message") if isinstance(err, dict) else (err if isinstance(err, str) else None)
        msg = msg or resp.text
    except Exception:
        msg = resp.text
    return redact(msg, secret, limit=300)


__all__ = ["post_json", "ProviderError"]
