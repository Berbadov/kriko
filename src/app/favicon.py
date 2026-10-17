"""A site's own icon, fetched once and kept as a decodable raster.

The desktop app draws a source row with a generated monogram because a screen
cannot fetch. The engine can, and GPUI can decode PNG, JPEG, WebP, GIF and SVG
bytes but has no ICO decoder — so this module's job is to hand back only bytes
the window can draw. It asks the site itself: the page's own `<link rel="icon">`
first, then the two names every site has had for twenty years.

Nothing here invents an icon service. A third party would mean every source the
reader looks at is announced to somebody else, and the site's own icon is the
only answer that is guaranteed to be about the site.

A favicon request is the one fetch whose destination the engine did not choose:
the host came from a source row, which came from a page. That is why `_public_host`
exists and why every hop is checked before it is opened.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

#: Long enough for a site behind a slow CDN, short enough that a missing icon
#: is a blank tile and not a stalled screen. Every hop gets its own budget.
TIMEOUT = 4.0

#: An icon is small. A body larger than this is a page, an error document, or
#: an attempt to make the reader pay for a download they did not ask for.
MAX_BYTES = 256 * 1024

#: The window's own eye for an icon: after a month, ask again. Sites change
#: their mark, and a cache with no expiry eventually draws last year's logo.
TTL = 30 * 24 * 60 * 60

USER_AGENT = "Kriko/1.0 (+https://github.com/Berbadov/kriko)"

#: What GPUI can decode, and the extension each kind is cached under. The
#: order is the lookup order, so a host cached before a format changed keeps
#: answering the same file rather than two.
_KINDS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}

_REDIRECTS = frozenset({301, 302, 303, 307, 308})

_LINK = re.compile(r"<link\b[^>]*>", re.I)
_ATTRIBUTE = re.compile(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*["']([^"']*)["']""")

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand a redirect back instead of following it unexamined."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(url: str, *, timeout: float = TIMEOUT):
    """The default transport: one request, with redirects left to `_get`.

    urllib follows a redirect before any caller can see the address it went to.
    The guard has to run between hops, so the default opener refuses to take
    the step itself.
    """
    request = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _public_host(host: str) -> str:
    """The host when it names a public address, otherwise "".

    The destination is not ours to trust: a source row can say `127.0.0.1`
    and mean the reader's router, a printer on the LAN, or a cloud metadata
    endpoint. So an IP literal, `localhost`, a single-label name and `.local`
    are refused outright, and a name is accepted only when *every* address it
    resolves to is globally routable. HTTPS only, because the fallback names
    are only meaningful on a site's real origin.
    """
    name = (host or "").strip().rstrip(".").casefold()
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    if not name or len(name) > 253 or "%" in name or "\\" in name:
        return ""
    if any(ord(char) < 33 for char in name):
        return ""
    if name == "localhost" or name.endswith(
        (".localhost", ".local", ".internal", ".home.arpa")
    ):
        return ""
    if "." not in name or ":" in name:
        return ""
    try:
        ipaddress.ip_address(name)
        return ""
    except ValueError:
        pass
    try:
        answers = socket.getaddrinfo(name, 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError, ValueError):
        return ""
    addresses = []
    for answer in answers:
        try:
            addresses.append(ipaddress.ip_address(str(answer[4][0]).split("%", 1)[0]))
        except (IndexError, TypeError, ValueError):
            return ""
    if not addresses or any(not address.is_global for address in addresses):
        return ""
    return name


def _public_url(value: str) -> str:
    """A URL only when it is HTTPS and its host passes `_public_host`."""
    try:
        parts = urllib.parse.urlsplit(str(value or "").strip())
        if parts.scheme.casefold() != "https":
            return ""
        if parts.username is not None or parts.password is not None:
            return ""
        host = parts.hostname or ""
    except ValueError:
        return ""
    if not _public_host(host):
        return ""
    return str(value).strip()


def _get(url: str, fetch) -> bytes | None:
    """One body, with every redirect hop checked before it is opened.

    A site whose icon moved answers `301`; following it blind would make the
    guard above a guard on the first address only. Each hop passes through
    `_public_url`, so a redirect to `https://127.0.0.1/` is refused exactly
    like an original request to it.
    """
    current = url
    for _ in range(4):
        checked = _public_url(current)
        if not checked:
            return None
        try:
            response = fetch(checked, timeout=TIMEOUT)
        except urllib.error.HTTPError as error:
            # urllib raises for a redirect the handler refused; the error is
            # still the response, with the Location this loop needs.
            response = error
        except (OSError, ValueError):
            return None
        try:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status in _REDIRECTS:
                location = str(response.headers.get("Location") or "").strip()
                if not location:
                    return None
                current = urllib.parse.urljoin(checked, location)
                continue
            if status is not None and not 200 <= int(status) < 300:
                return None
            return response.read(MAX_BYTES + 1)[:MAX_BYTES]
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
    return None


def sniff(data: bytes) -> str | None:
    """The content type of a supported image, read from its magic bytes.

    The server's own `Content-Type` is not consulted: a `.ico` is routinely
    served as `image/x-icon` or `image/vnd.microsoft.icon`, and an HTML error
    page as `image/png`. The bytes are the only statement that cannot be
    wrong.
    """
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:512]
    if head.startswith(b"<svg") or (
        head.startswith(b"<?xml") and b"<svg" in head
    ):
        return "image/svg+xml"
    return None


def png_from_ico(data: bytes) -> bytes | None:
    """The largest PNG frame inside an ICO, or None.

    Modern ICO files are a directory over frames that may be BMP or PNG. GPUI
    has no ICO format, but a PNG frame is already the format it wants, so the
    container is read here and nothing is re-encoded. A file whose largest
    frame is BMP is refused rather than converted: there is no decoder here.
    """
    if len(data) < 6 or data[:4] != b"\x00\x00\x01\x00":
        return None
    count = struct.unpack_from("<H", data, 4)[0]
    if count == 0 or len(data) < 6 + count * 16:
        return None
    frames = []
    for index in range(count):
        at = 6 + index * 16
        width, height, _colours, _reserved, _planes, _bits, size, offset = (
            struct.unpack_from("<BBBBHHII", data, at)
        )
        # A zero dimension means 256 in an ICO directory.
        area = (width or 256) * (height or 256)
        if size and offset + size <= len(data):
            frames.append((area, offset, size))
    for _area, offset, size in sorted(frames, reverse=True):
        frame = data[offset : offset + size]
        if frame.startswith(_PNG_MAGIC):
            return frame
    return None


def decode(data: bytes) -> tuple[bytes, str] | None:
    """Bytes as something GPUI can draw, or None for a format it cannot."""
    kind = sniff(data)
    if kind is not None:
        return data, kind
    frame = png_from_ico(data)
    if frame is not None:
        return frame, "image/png"
    return None


def _declared(page: str) -> list[str]:
    """The icon hrefs a page declares, in the page's own order.

    `rel="shortcut icon"`, `rel="icon"` and both apple-touch spellings all
    name a mark; a `mask-icon` does not, because it is an alpha-only shape
    meant to be filled by the browser's own colour.
    """
    found = []
    for tag in _LINK.findall(page):
        attributes = {
            name.casefold(): html.unescape(value)
            for name, value in _ATTRIBUTE.findall(tag)
        }
        rels = attributes.get("rel", "").casefold().split()
        href = attributes.get("href", "").strip()
        if href and (
            "icon" in rels
            or "apple-touch-icon" in rels
            or "apple-touch-icon-precomposed" in rels
        ):
            found.append(href)
    return found


def _cached(cache_dir: Path, host: str) -> tuple[bytes, str] | None:
    """A fresh cached icon, read without a network call."""
    stem = hashlib.sha1(host.encode("utf-8")).hexdigest()
    for kind, extension in _KINDS.items():
        path = Path(cache_dir) / f"{stem}{extension}"
        try:
            if time.time() - path.stat().st_mtime >= TTL:
                continue
            return path.read_bytes(), kind
        except OSError:
            continue
    return None


def _store(cache_dir: Path, host: str, body: bytes, kind: str) -> None:
    """Write the icon under the host's hash, best effort.

    A cache that cannot be written is a slower window, never a broken one, so
    a read-only home directory is swallowed here rather than turning a row
    into an error.
    """
    stem = hashlib.sha1(host.encode("utf-8")).hexdigest()
    directory = Path(cache_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for other in _KINDS.values():
            if other != _KINDS[kind]:
                (directory / f"{stem}{other}").unlink(missing_ok=True)
        (directory / f"{stem}{_KINDS[kind]}").write_bytes(body)
    except OSError:
        pass


def icon_for(
    host: str,
    *,
    fetch=_open,
    cache_dir: Path,
) -> tuple[bytes, str] | None:
    """The icon bytes for `host` and their content type, or None.

    The page is asked first because that is where a site records the mark it
    actually uses, including the size it wants on a retina screen. The two
    well-known names are the fallback for a site that records nothing. A
    cached icon short-circuits all of it: the second row for a host costs a
    file read, not a request.
    """
    name = (host or "").strip().rstrip(".").casefold()
    if not name:
        return None
    hit = _cached(cache_dir, name)
    if hit is not None:
        return hit
    if not _public_host(name):
        return None

    base = f"https://{name}/"
    candidates: list[str] = []
    page = _get(base, fetch)
    if page is not None:
        for href in _declared(page.decode("utf-8", "replace")):
            url = urllib.parse.urljoin(base, href)
            if url not in candidates:
                candidates.append(url)
    for fallback in (f"{base}favicon.ico", f"{base}apple-touch-icon.png"):
        if fallback not in candidates:
            candidates.append(fallback)

    for url in candidates:
        body = _get(url, fetch)
        if not body:
            continue
        icon = decode(body)
        if icon is None:
            continue
        encoded, kind = icon
        _store(cache_dir, name, encoded, kind)
        return encoded, kind
    return None
