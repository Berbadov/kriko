"""Fetching a page a stranger asked for, without becoming a way into the operator's network.

A relay that fetches addresses it was handed is a server-side request forgery
waiting for a request: `http://169.254.169.254/` (a cloud host's credentials),
`http://localhost:8000/` (the relay's own database port) or a redirect from an
innocent page to either. So nothing is fetched until its host resolves only to
public addresses, the same is checked at every redirect, and the answer is
bounded in size, time and type.

Resolution happens here and the connection happens in urllib a moment later, so a
hostile name server could answer differently the second time. Run the relay in a
container with no route to anything private (the README does) and this is the
second wall, not the only one.
"""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_BYTES = 2_000_000
TIMEOUT = 15.0
#: The whole page, not one wait on the socket: a server that sends a byte a second
#: never trips `TIMEOUT` and would hold the one sweeper thread for every watch.
BUDGET = 30.0
MAX_REDIRECTS = 4
PORTS = (None, 80, 443)
USER_AGENT = "Kriko-Cloud/1.0 (+https://github.com/Berbadov/kriko)"


class Refused(ValueError):
    """The address is not one the relay will fetch."""


def check(url: str) -> str:
    """The host, when `url` may be fetched; `Refused` saying why when it may not."""
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in ("http", "https"):
        raise Refused("only http and https pages")
    if parts.username or parts.password:
        raise Refused("no credentials in an address")
    host = (parts.hostname or "").strip(".")
    if not host:
        raise Refused("no host")
    try:
        port = parts.port
    except ValueError as error:
        raise Refused("bad port") from error
    if port not in PORTS:
        raise Refused("only the ordinary web ports")
    try:
        found = {str(item[4][0]) for item in socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80),
                                                              type=socket.SOCK_STREAM)}
    except OSError as error:
        raise Refused("the host does not resolve") from error
    if not found:
        raise Refused("the host does not resolve")
    for address in found:
        if not _public(address):
            raise Refused("the host is not on the public internet")
    return host.lower()


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip in _NAT64:
        # 64:ff9b::a9fe:a9fe is 169.254.169.254 to a NAT64 gateway: judge the address inside.
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF).is_global
    return ip.is_global


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read(response) -> bytes:  # type: ignore[no-untyped-def]
    """At most `MAX_BYTES`, within `BUDGET` seconds in all; what arrived by then is kept."""
    deadline = time.monotonic() + BUDGET
    chunks: list[bytes] = []
    size = 0
    while size < MAX_BYTES and time.monotonic() < deadline:
        chunk = response.read(min(65536, MAX_BYTES - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def markup(url: str) -> str:
    """The page's markup, or "" when it will not come. Never raises for a bad page."""
    try:
        check(url)
        opener = urllib.request.build_opener(_Redirects)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"})
        with opener.open(request, timeout=TIMEOUT) as response:
            kind = (response.headers.get_content_type() or "").lower()
            if kind and not (kind.startswith("text/") or "html" in kind or "xml" in kind):
                return ""
            raw = _read(response)
            charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, "replace")
    except (Refused, urllib.error.URLError, TimeoutError, OSError, ValueError, LookupError):
        return ""
