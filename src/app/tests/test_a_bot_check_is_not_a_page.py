"""A 200 that holds a bot check is a refusal, and climbs the ladder.

Measured on a quick look for a drive with plenty of forum threads: TechPowerUp
answered 145 characters ("Drag the handle to the target") and Tom's Hardware
89 ("Checking your browser"). Both were counted as read pages and took the
places of real ones, because the ladder only climbed on 403/429/503.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.providers import browser, fetch, pagereader

CHECK = "<html><head><title>Just a moment...</title></head><body><p>Checking your browser before accessing the site.</p></body></html>"
ARTICLE = "<html><body><main>" + "<p>The drive failed after four months and the vendor replaced it. </p>" * 30 + "</main></body></html>"
SHORT_REAL = "<html><body><p>Two weeks in, the drive was blocked by the BIOS until I updated.</p></body></html>"


@pytest.fixture
def site():
    pages = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path, "").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    pages["base"] = f"http://127.0.0.1:{server.server_port}"
    yield pages
    server.shutdown()


@pytest.fixture
def rungs(monkeypatch):
    called = []
    monkeypatch.setattr(pagereader, "read",
                        lambda url, endpoint="", timeout=0, **_: called.append("hosted") or "")
    monkeypatch.setattr(browser, "read",
                        lambda url, timeout=0, **_: called.append("browser") or "")
    return called


def test_a_bot_check_answered_200_climbs_the_ladder_and_is_not_kept(site, rungs):
    site["/check"] = CHECK
    assert fetch.reader(timeout=10.0)(site["base"] + "/check", allow_private=True).text == ""
    assert rungs[0] == "hosted"


def test_a_quick_look_drops_a_bot_check_without_starting_fallbacks(site, rungs):
    site["/check"] = CHECK
    page = fetch.reader(timeout=10.0)(site["base"] + "/check", allow_fallback=False,
                                      allow_private=True)
    assert page.text == ""
    assert rungs == []


def test_a_bot_check_hidden_in_a_large_page_is_still_a_bot_check(site, rungs):
    # The real one was 118 KB of markup around 145 characters of words.
    site["/big"] = ("<html><head><script>" + "x=1;" * 30000
                    + "</script></head><body><p>Verifying your connection.</p>"
                    "<p>Drag the handle to the target</p></body></html>")
    assert fetch.reader(timeout=10.0)(site["base"] + "/big", allow_private=True).text == ""
    assert rungs[0] == "hosted"


def test_a_rung_that_reads_the_page_replaces_the_bot_check(site, monkeypatch):
    site["/check"] = CHECK
    monkeypatch.setattr(pagereader, "read",
                        lambda url, endpoint="", timeout=0, **_: "the real thread text")
    assert fetch.reader(timeout=10.0)(site["base"] + "/check", allow_private=True).text == "the real thread text"


def test_an_ordinary_page_is_read_plainly_and_climbs_nothing(site, rungs):
    site["/a"] = ARTICLE
    assert "failed after four months" in fetch.reader(timeout=10.0)(
        site["base"] + "/a", allow_private=True).text
    assert rungs == []


def test_a_short_real_page_that_says_blocked_in_one_sentence_is_still_a_check_by_shape():
    # Short and in the words of a block page: the cost of being wrong is one
    # more rung, and the page is not lost (a rung that reads it returns it).
    assert fetch.challenged("Checking your browser before accessing")
    assert not fetch.challenged("")
    assert not fetch.challenged("word " * 400 + " blocked by the firewall")
