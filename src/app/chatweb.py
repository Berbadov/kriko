"""A bounded public page reader for Chat's web source.

Search results and reader supplied links are untrusted destinations. Before
each request, including every redirect hop, resolve the host and refuse the
request if any returned address is not globally routable. Redirects are
handled one hop at a time so a redirect cannot skip that check.
"""

from __future__ import annotations

import ipaddress
import io
import socket
import urllib.error
import urllib.parse
import urllib.request
from functools import partial

from app.providers import fetch, network, proxypool, transport
from kriko.research import Fetched

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
REDIRECTS = frozenset({301, 302, 303, 307, 308})
USER_AGENT = "Kriko/1.0 (+https://github.com/Berbadov/kriko)"


def _public_url(value: object) -> str:
    """Return a URL only when its host resolves exclusively to public IPs."""
    url = str(value or "").strip()
    if not url or len(url) > 2000 or any(ord(ch) < 32 for ch in url) or "\\" in url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.casefold()
        host = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port or (443 if scheme == "https" else 80)
        if (scheme not in {"http", "https"} or not host or port < 1 or port > 65535
                or parsed.username is not None or parsed.password is not None
                or host == "localhost" or host.endswith(".localhost")
                or "%" in host):
            return ""
    except ValueError:
        return ""

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return url if literal.is_global else ""

    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError, ValueError):
        return ""
    addresses = []
    for answer in answers:
        try:
            address = ipaddress.ip_address(str(answer[4][0]).split("%", 1)[0])
        except (IndexError, TypeError, ValueError):
            return ""
        addresses.append(address)
    if not addresses or any(not address.is_global for address in addresses):
        return ""
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Expose one redirect response to the caller for checked re-opening."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_one(url: str, timeout: float, via=None):
    """Open one request, returning HTTPError redirects as response objects.

    `via` is an opener that connects through a proxy (`proxypool.Router.opener`).
    """
    opener = via or transport.opener(_NoRedirect())
    request = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as response:
        # HTTPError implements the response interface and carries Location.
        # The outer network wrapper then holds its permit until it is closed.
        return response


def _open(current: str, timeout: float, checker, router):
    """The response for one hop, or None when the page cannot be read.

    Direct, as it always was. With a proxy pool on (Settings, off by default)
    a host is read through the pool only after a direct read of it was
    measured as refused (403, 429) or answered a bot check
    (`proxypool.should_route`): nothing here names a site.
    """
    host = urllib.parse.urlsplit(current).hostname or ""

    def direct():
        return network.urlopen(current, timeout=timeout, check=checker, opener=_open_one)

    if router is None:
        return direct()
    if not router.should_route(host):
        response = direct()
        if response.getcode() not in proxypool.BLOCK_STATUSES:
            return response
        response.close()
        router.note_blocked(host)
    if not router.robots_allow(current):
        router.say(f"{host}: robots.txt asks not to be read, so it was not retried through a proxy")
        router.note("unreadable")
        return None
    tried = router.candidates()
    if not tried:
        router.say(f"{host}: no healthy proxy is left; reading directly")
        router.note("direct_fallbacks")
        return direct()
    for proxy in tried:
        if checker is not None:
            checker()
        via = router.opener(proxy, _NoRedirect())
        try:
            response = network.urlopen(current, timeout=timeout, check=checker,
                                       opener=partial(_open_one, via=via))
        except (urllib.error.URLError, OSError) as error:
            router.retire(proxy, type(getattr(error, "reason", error)).__name__)
            continue
        code = response.getcode()
        if code in proxypool.PROXY_FAILURES:
            response.close()
            router.retire(proxy, f"HTTP {code}")
            continue
        if code in proxypool.BLOCK_STATUSES:
            response.close()
            continue
        router.say(f"{host}: read through {router.label(proxy)}")
        router.note("proxied_reads")
        return response
    router.say(f"{host}: could not be read, still blocked after {len(tried)} proxies")
    router.note("unreadable")
    return None


def reader(timeout: float = 5.0, *, check_cancelled=None, proxies=None):
    """Make a `fetch.reader` compatible callable with public-hop validation.

    `proxies` is `proxypool.reader_options()["proxies"]` when the reader has
    turned the pool on, and absent otherwise, which is every other case.
    """

    def read(url: str) -> Fetched:
        current = str(url or "")
        checker = check_cancelled or getattr(read, "check_cancelled", None)
        for hop in range(MAX_REDIRECTS + 1):
            if checker is not None:
                checker()
            current = _public_url(current)
            if not current:
                return Fetched("")
            if checker is not None:
                checker()
            try:
                opened = _open(current, timeout, checker, proxies)
                if opened is None:
                    return Fetched("")
                with opened as response:
                    status = response.getcode()
                    if status in REDIRECTS:
                        location = str(response.headers.get("Location") or "").strip()
                        if not location or hop >= MAX_REDIRECTS:
                            return Fetched("")
                        next_url = urllib.parse.urljoin(current, location)
                    elif status is None or not 200 <= int(status) < 300:
                        return Fetched("")
                    else:
                        content_type = (response.headers.get_content_type() or "").lower()
                        if content_type == "application/pdf":
                            from pypdf import PdfReader
                            raw = response.read(MAX_BYTES + 1)
                            if len(raw) > MAX_BYTES:
                                return Fetched("")
                            try:
                                document = PdfReader(io.BytesIO(raw), strict=False)
                                if document.is_encrypted:
                                    return Fetched("")
                                pages = []
                                count = 0
                                for number, page in enumerate(document.pages[:80], 1):
                                    if checker is not None:
                                        checker()
                                    piece = (page.extract_text() or "")[:30000]
                                    if piece.strip():
                                        pages.append(f"Page {number}:\n{piece}")
                                    count += len(piece)
                                    if count >= 200000:
                                        break
                                return Fetched("\n\n".join(pages))
                            except Exception:
                                return Fetched("")
                        if content_type and not (
                            content_type.startswith("text/")
                            or "html" in content_type
                            or "xml" in content_type
                        ):
                            return Fetched("")
                        charset = response.headers.get_content_charset() or "utf-8"
                        markup = response.read(MAX_BYTES).decode(charset, "replace")
                        text = fetch.to_text(markup)
                        if fetch.challenged(text):
                            if proxies is not None:
                                proxies.note_blocked(urllib.parse.urlsplit(current).hostname or "")
                            return Fetched("")
                        image = _public_url(fetch.image_url(markup, current))
                        return Fetched(text, fetch.published_at(markup), image)
            except (urllib.error.URLError, TimeoutError, OSError,
                    LookupError, ValueError, socket.gaierror):
                return Fetched("")
            current = next_url
        return Fetched("")

    return read
