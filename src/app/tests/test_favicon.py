"""Site icons: what the engine will fetch, what it will not, and what it keeps.

The destination of a favicon request is not chosen by the engine — it is
whatever host a source row names. That makes the guard the first thing worth
testing, before the parsing that only runs after it. The rest covers the two
formats that decide whether GPUI can draw anything at all: a PNG read from
its magic, and a PNG frame lifted out of an ICO that GPUI cannot decode.

No test here reaches the network. The guard is exercised with an injected DNS
answer, and every fetch is a fake that records the URLs it was asked for.
"""

from __future__ import annotations

import hashlib
import socket
import struct

import pytest
from fastapi.testclient import TestClient

from app import favicon
from app.web.app import create_app
from app.web.settings import Settings

PNG = b"\x89PNG\r\n\x1a\n" + b"a small tile"
PNG_LARGE = b"\x89PNG\r\n\x1a\n" + b"a larger tile"
ICO_PNG_MAGIC = b"\x00\x00\x01\x00"


class Reply:
    """The little of an HTTP response the reader touches."""

    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        pass


class Site:
    """A fake origin: URLs to answers, and a record of every ask."""

    def __init__(self, routes: dict[str, bytes | Reply]):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float = 4.0) -> Reply:
        self.calls.append(url)
        answer = self.routes.get(url)
        if answer is None:
            return Reply(b"not found", status=404)
        if isinstance(answer, Reply):
            return answer
        return Reply(answer)


@pytest.fixture
def public_dns(monkeypatch):
    """One public address for every name, so no test resolves a real host."""

    def resolve(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(favicon.socket, "getaddrinfo", resolve)


def ico(frames: list[tuple[int, int, bytes]]) -> bytes:
    """An ICO directory over `frames`, the way a real file lays them out."""
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    body = b""
    for width, height, data in frames:
        entries += struct.pack(
            "<BBBBHHII",
            width if width < 256 else 0,
            height if height < 256 else 0,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        offset += len(data)
        body += data
    return header + entries + body


# ── the guard ──────────────────────────────────────────────────────────────


def test_an_ip_literal_is_refused():
    """A source row can say anything; `127.0.0.1` is the router's front page."""
    for literal in ("127.0.0.1", "10.1.2.3", "192.168.0.1", "169.254.169.254"):
        assert favicon._public_host(literal) == ""
    assert favicon._public_host("::1") == ""
    assert favicon._public_host("[::1]") == ""


def test_localhost_and_a_lan_name_are_refused():
    for name in ("localhost", "localhost.", "printer.local", "router.internal"):
        assert favicon._public_host(name) == ""
    # A single label is a machine on this network, not a public site.
    assert favicon._public_host("testserver") == ""


def test_a_name_that_resolves_private_is_refused(monkeypatch):
    monkeypatch.setattr(
        favicon.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 443))
        ],
    )
    assert favicon._public_host("camera.example") == ""


def test_a_public_name_is_accepted(public_dns):
    assert favicon._public_host("Gear.Example.") == "gear.example"


# ── the bytes ──────────────────────────────────────────────────────────────


def test_a_png_is_read_from_its_magic_bytes():
    assert favicon.sniff(PNG) == "image/png"
    assert favicon.sniff(b"GIF89a....") == "image/gif"
    assert favicon.sniff(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>") == "image/svg+xml"
    assert favicon.sniff(b"<html>not an icon</html>") is None


def test_the_largest_png_frame_is_lifted_out_of_an_ico():
    smaller = PNG
    larger = PNG_LARGE
    container = ico([(16, 16, smaller), (32, 32, larger)])
    assert favicon.png_from_ico(container) == larger


def test_an_ico_without_a_png_frame_is_refused():
    """A BMP frame is an ICO GPUI cannot draw, so it is a monogram instead."""
    container = ico([(32, 32, b"\x28\x00\x00\x00" + b"\x00" * 64)])
    assert favicon.png_from_ico(container) is None


# ── the cache ──────────────────────────────────────────────────────────────


def test_a_cached_icon_is_returned_without_a_second_fetch(tmp_path, public_dns):
    site = Site(
        {
            "https://gear.example/": b"<html><link rel=\"icon\" href=\"/mark.png\"></html>",
            "https://gear.example/mark.png": PNG,
        }
    )
    first = favicon.icon_for("gear.example", fetch=site, cache_dir=tmp_path)
    assert first == (PNG, "image/png")
    assert site.calls == ["https://gear.example/", "https://gear.example/mark.png"]

    calls = len(site.calls)
    second = favicon.icon_for("gear.example", fetch=site, cache_dir=tmp_path)
    assert second == (PNG, "image/png")
    assert len(site.calls) == calls, "a cached icon must not hit the network"

    name = hashlib.sha1(b"gear.example").hexdigest()
    assert (tmp_path / f"{name}.png").read_bytes() == PNG


def test_a_redirect_to_a_private_address_is_not_followed(tmp_path, public_dns):
    site = Site(
        {
            "https://gear.example/": Reply(
                b"", status=302, headers={"Location": "https://127.0.0.1/icon.png"}
            ),
        }
    )
    assert favicon.icon_for("gear.example", fetch=site, cache_dir=tmp_path) is None
    assert "https://127.0.0.1/icon.png" not in site.calls


# ── the route ──────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app) as client:
        yield client


def test_the_route_says_when_there_is_no_icon(client):
    reply = client.get("/api/favicon", params={"host": "localhost"})
    assert reply.status_code == 404
    assert "No icon" in reply.text


def test_the_route_returns_the_icon_with_its_type(client, monkeypatch):
    monkeypatch.setattr(favicon, "icon_for", lambda host, *, cache_dir: (PNG, "image/png"))
    reply = client.get("/api/favicon", params={"host": "gear.example"})
    assert reply.status_code == 200
    assert reply.headers["content-type"] == "image/png"
    assert reply.content == PNG
