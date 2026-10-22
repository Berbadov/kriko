"""A service that accepts the connection and then drips must not hold a search.

The reader's words: the in-house web search "fails alot". OpenSERP's own notes
already call the engines iffy (challenges, timeouts, an engine answering empty
about half the time), and the chain behind it was built for exactly that. What
neither had was a *whole-body* deadline: `urlopen`'s timeout bounds each wait on
the socket, not the answer, so a service that sends a byte every few seconds
never trips it. `fetch._body` was given a deadline for this
(`test_a_page_read_is_bounded_in_wall_clock.py`, measured: 48 s on an 8 s
budget); `_http` — the one door every hosted provider goes through — and the
chain above it had none.

These are the reproductions, at the three levels the failure was reachable: a
response that drips, a real HTTP service that drips, and a chain member that
never returns at all.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.providers import _http, websearch
from kriko.research.politeness import LocalSearchError


class Dripping:
    """A response that gives a little at a time, slowly, for a long while."""

    def __init__(self, pause: float = 0.05, pieces: int = 200):
        self.pause = pause
        self.pieces = pieces
        self.calls = 0

    def read(self, size: int = -1) -> bytes:
        self.calls += 1
        if self.calls > self.pieces:
            return b""
        time.sleep(self.pause)
        return b"x"

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_provider_that_drips_is_cut_at_its_whole_body_deadline():
    response = Dripping(pause=0.05)
    began = time.monotonic()

    body, why = _http._read_body(response, timeout=0.3)

    assert time.monotonic() - began < 1.0, "the per-recv timeout never fires on a drip"
    assert body, "what arrived before the deadline is kept"
    assert "within" in why, "the reason says the answer did not finish in time"


def test_a_provider_that_answers_is_read_whole():
    class Whole:
        parts = [b'{"a":', b" 1}"]

        def read(self, size=-1):
            return self.parts.pop(0) if self.parts else b""

    body, why = _http._read_body(Whole(), timeout=5.0)
    assert body == b'{"a": 1}' and why == ""


class _DrippingService(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    pause = 0.02
    pieces = 200

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(self.pieces))
        self.end_headers()
        for _ in range(self.pieces):
            try:
                self.wfile.write(b"x")
                self.wfile.flush()
            except OSError:
                return
            time.sleep(self.pause)

    def log_message(self, *_):
        pass


@pytest.fixture
def dripping_service():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DrippingService)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1/search"
    server.shutdown()
    server.server_close()


def test_a_hosted_provider_that_drips_does_not_hold_the_turn(dripping_service):
    began = time.monotonic()

    payload, why = _http.post_json_or_why(dripping_service, {}, {}, timeout=0.6)

    assert time.monotonic() - began < 3.0
    assert payload == {}
    assert "within" in why and "127.0.0.1" in why


def test_the_hosted_page_reader_that_drips_gives_the_page_up(dripping_service):
    """The ladder's hosted rung pays the same bounded budget as any provider."""
    from app.providers import pagereader

    began = time.monotonic()
    body, session = pagereader._rpc(dripping_service, {"method": "initialize"},
                                    timeout=0.6)

    assert time.monotonic() - began < 3.0
    assert body == {}, "a reader that did not finish answering read no page"


def test_a_provider_behind_a_dripping_one_still_answers(dripping_service):
    """The chain moves on instead of waiting for a service that will not finish."""
    def dripping(query, limit=5, **_options):
        payload = _http.post_json(dripping_service, {"query": query}, {}, timeout=0.6)
        if not payload:
            raise LocalSearchError("the service dripped and never finished")
        return [{"url": "https://drip.test/x", "title": "drip"}]

    def quick(query, limit=5, **_options):
        return [{"url": "https://fast.test/x", "title": "fast"}]

    chain = websearch.Chain([("openserp", lambda: dripping), ("deepseek", lambda: quick)],
                            log=lambda _line: None)
    began = time.monotonic()

    hits = chain("a query", 5, timeout=3.0)

    assert time.monotonic() - began < 5.0
    assert [hit["url"] for hit in hits] == ["https://fast.test/x"]


def test_a_chain_member_that_never_answers_is_abandoned_at_the_budget():
    released = threading.Event()

    def never(query, limit=5, **_options):
        released.wait(10)
        return [{"url": "https://late.test/x", "title": "late"}]

    said: list[str] = []
    chain = websearch.Chain([("openserp", lambda: never)], log=said.append)
    began = time.monotonic()
    try:
        with pytest.raises(LocalSearchError) as caught:
            chain("a query", 5, timeout=0.4)
    finally:
        released.set()

    assert time.monotonic() - began < 2.0
    assert "did not answer within" in str(caught.value)
    assert any("did not answer within" in line for line in said)


def test_a_stalling_first_provider_hands_the_query_to_the_one_behind_it():
    released = threading.Event()

    def never(query, limit=5, **_options):
        released.wait(10)
        return [{"url": "https://late.test/x", "title": "late"}]

    def quick(query, limit=5, **_options):
        return [{"url": "https://fast.test/x", "title": "fast"}]

    said: list[str] = []
    chain = websearch.Chain([("openserp", lambda: never), ("deepseek", lambda: quick)],
                            log=said.append)
    began = time.monotonic()
    try:
        hits = chain("a query", 5, timeout=1.0)
    finally:
        released.set()

    assert time.monotonic() - began < 3.0
    assert [hit["url"] for hit in hits] == ["https://fast.test/x"]
    assert any("OpenSERP" in line and "within" in line for line in said)
