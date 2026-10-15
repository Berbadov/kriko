"""A Google result is its page, once the click-through is followed.

The adapter dropped every `google.com/goto?url=<token>` link on the belief
that it carries no address. Google answers it with a plain 302 to the page,
and Google answered every query when the other engines timed out or came back
empty. Dropping its links left a run with nothing to read.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.providers import openserp

GOTO = "https://www.google.com/goto?url=CAESnAEB6zswFefD9OonD72Og"


@pytest.fixture
def door():
    """A loopback server: /to/<n> redirects to a page, /page answers 200,
    /loop redirects back into a Google click-through."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/to/"):
                self.send_response(302)
                self.send_header("Location", f"https://forum.test/thread/{self.path[4:]}")
            elif self.path == "/loop":
                self.send_response(302)
                self.send_header("Location", GOTO)
            else:
                self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_the_redirect_is_reported_not_followed(door):
    assert openserp.unwrap_goto(f"{door}/to/7") == "https://forum.test/thread/7"


def test_a_page_that_answers_instead_of_redirecting_has_nothing_to_unwrap(door):
    assert openserp.unwrap_goto(f"{door}/page") == ""


def test_a_redirect_back_into_a_click_through_is_not_an_answer(door):
    assert openserp.unwrap_goto(f"{door}/loop") == ""


def test_an_unreachable_link_is_dropped_not_raised():
    assert openserp.unwrap_goto("http://127.0.0.1:1/x", timeout=1.0) == ""


def test_only_the_wrapped_hits_are_resolved_and_order_is_kept():
    asked = []

    def resolve(url, check=None):
        asked.append(url)
        return "https://forum.test/a" if url == GOTO else ""

    plain = {"url": "https://other.test/p", "title": "plain"}
    hits = [plain, {"url": GOTO, "title": "wrapped"}, {"url": GOTO + "2", "title": "dead"}]
    out = openserp._unwrapped(hits, resolve=resolve)
    assert [hit["url"] for hit in out] == ["https://other.test/p", "https://forum.test/a", ""]
    assert sorted(asked) == [GOTO, GOTO + "2"]
    assert out[0] is plain


def test_a_search_returns_the_page_behind_a_google_hit_and_drops_a_dead_one(monkeypatch):
    class Reply:
        def __init__(self, payload):
            import json
            self._body = json.dumps(payload).encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    payload = {"results": [
        {"url": GOTO, "title": "Crucial MX500 suddenly dead", "domain": "google.com"},
        {"url": GOTO + "x", "title": "unreadable", "domain": "google.com"},
        {"url": "https://example.test/b", "title": "b", "domain": "example.test"},
    ], "meta": {}}
    monkeypatch.setattr(openserp.urllib.request, "urlopen",
                        lambda request, timeout=None: Reply(payload))
    search = openserp.searcher(
        engine="google",
        resolve=lambda url, check=None: "https://forum.test/mx500" if url == GOTO else "")
    hits = search("crucial mx500")
    assert [hit["url"] for hit in hits] == ["https://forum.test/mx500", "https://example.test/b"]
    assert hits[0]["site"] == "forum.test"
