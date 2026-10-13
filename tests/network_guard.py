"""Offline tests permit only literal loopback/AF_UNIX for asyncio infrastructure.
No win32 exemption: DNS, TCP, UDP and real HTTP transports are guarded.
"""

import ipaddress, socket


def install(monkeypatch):
    def allowed(sock, address):
        if sock.family == getattr(socket, "AF_UNIX", object()):
            return True
        try:
            return ipaddress.ip_address(address[0]).is_loopback
        except (ValueError, TypeError, IndexError):
            return False

    for name in ("connect", "connect_ex", "sendto"):
        original = getattr(socket.socket, name)

        def guarded(self, *args, _original=original, _name=name, **kw):
            address = args[-1] if _name == "sendto" else args[0]
            if not allowed(self, address):
                raise AssertionError("External network forbidden in offline tests")
            return _original(self, *args, **kw)

        monkeypatch.setattr(socket.socket, name, guarded)
    original_dns = socket.getaddrinfo

    def dns(host, *args, **kw):
        if host is None:
            return original_dns(host, *args, **kw)
        if host in ("localhost", b"localhost"):
            return original_dns(host, *args, **kw)
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            raise AssertionError("External DNS forbidden in offline tests") from None
        if not literal.is_loopback:
            raise AssertionError("External DNS forbidden in offline tests")
        return original_dns(host, *args, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    # Keep test behavior independent of machine proxy configuration.
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
