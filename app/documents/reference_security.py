"""Defence in depth for automatic references. HTTPX cannot pin validated DNS answers.
Exact host allowlist + HTTPS + all DNS answers public + every redirect validated.
Deploy behind public-only egress filtering to close DNS rebinding/TOCTOU exposure.
"""

from ipaddress import ip_address
import socket
from urllib.parse import urlsplit, urlunsplit, parse_qsl
import re


def fulfilment_attachment(url):
    """Only the observed GeM tender attachment endpoint and package-bound path."""
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname!='fulfilment.gem.gov.in' or p.port not in (None,443) or contains_credentials(url):return None
        if p.path!='/contract/slafds':return None
        query=parse_qsl(p.query,keep_blank_values=True)
        if len(query)!=1 or query[0][0]!='fileDownloadPath':return None
        value=query[0][1]
        if '\\' in value or '%' in value or any(x in {'.','..'} for x in value.split('/')):return None
        match=re.fullmatch(r'SLA_UPLOAD_PATH/(\d{4})/[A-Za-z]{3}/GEM_(\d{4})_([BR])_(\d+)/(?:[A-Za-z0-9_-]+/){0,3}([A-Za-z0-9_@(). -]+\.(?:pdf|docx|xlsx|csv|txt|png|jpe?g|doc|xls|zip))',value,re.I)
        if not match:return None
        return {'bid':f'GEM/{match[2]}/{match[3].upper()}/{match[4]}','filename':match[5]}
    except ValueError:return None
from app.documents.downloader import URLValidationError


def contains_credentials(url):
    try:
        p = urlsplit(url)
        return (
            p.username is not None
            or p.password is not None
            or any(
                any(
                    secret in k.lower()
                    for secret in (
                        "token",
                        "password",
                        "secret",
                        "credential",
                        "signature",
                        "api_key",
                        "authorization",
                    )
                )
                or k.lower() in {"key", "sig", "auth"}
                for k, v in parse_qsl(p.query)
            )
        )
    except ValueError:
        return True


def canonical_url(url):
    p = urlsplit(url)
    host = (p.hostname or "").lower().rstrip(".")
    port = p.port
    netloc = host if ":" not in host else f"[{host}]"
    if port and not (
        (p.scheme.lower() == "https" and port == 443)
        or (p.scheme.lower() == "http" and port == 80)
    ):
        netloc += f":{port}"
    # Never erase userinfo to turn a forbidden URL into an allowed one.
    if contains_credentials(url):
        raise ValueError("userinfo is forbidden")
    return urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))


class AutomaticURLPolicy:
    def __init__(self, settings, resolver=None):
        self.hosts = {
            h.strip().lower().rstrip(".")
            for h in settings.document_reference_allowed_hosts.split(",")
            if h.strip()
        }
        self.https = settings.document_reference_require_https
        self.resolver = resolver or socket.getaddrinfo

    def validate(self, url, *, resolve=True):
        try:
            if len(url) > 8192 or any(ord(c) < 33 for c in url) or "\\" in url:
                raise ValueError("invalid URL characters or length")
            value = canonical_url(url)
            p = urlsplit(value)
            if p.scheme not in ({"https"} if self.https else {"http", "https"}):
                raise ValueError("scheme not permitted")
            if p.hostname not in self.hosts or p.port not in (None, 443, 80):
                raise ValueError("host or port not allowlisted")
            if p.hostname=='fulfilment.gem.gov.in' and not fulfilment_attachment(value):
                raise ValueError('not an authoritative attachment endpoint')
            if resolve:
                answers = self.resolver(
                    p.hostname,
                    p.port or (443 if p.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
                if not answers or any(
                    not ip_address(a[4][0]).is_global
                    or ip_address(a[4][0]).is_multicast
                    or ip_address(a[4][0]).is_reserved
                    for a in answers
                ):
                    raise ValueError("DNS destination is not public")
            return value
        except (ValueError, OSError) as exc:
            # Do not reflect URLs, queries, passwords or DNS infrastructure in logs.
            raise URLValidationError(
                "UNSAFE_REFERENCE_URL",
                "Automatic reference URL rejected by security policy",
            ) from exc
