"""A page costs the run at most a bounded time, however the host behaves.

The quick look's reader was given 8 seconds and a refused or dripping page
took 48 (one 429 climbed two rungs of 45 s each; a server sending a byte
every few seconds never tripped the socket timeout). Every page the run waits
for is a page it is not reading.
"""

import time

from app.providers import browser, fetch, pagereader


class Dripping:
    """A response that gives a little at a time, slowly, forever."""

    def __init__(self, pause: float):
        self.pause = pause
        self.calls = 0

    def read(self, size: int = -1) -> bytes:
        self.calls += 1
        time.sleep(self.pause)
        return b"<p>words</p>"


def test_a_page_that_drips_is_cut_at_the_budget_and_what_arrived_is_kept():
    response = Dripping(pause=0.05)
    started = time.monotonic()
    body = fetch._body(response, timeout=0.3)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0
    assert body.startswith(b"<p>words</p>")
    assert response.calls < 20


def test_a_page_that_ends_is_read_whole():
    class Whole:
        parts = [b"abc", b"def", b""]

        def read(self, size=-1):
            return self.parts.pop(0)

    assert fetch._body(Whole(), timeout=5.0) == b"abcdef"


def test_a_refused_page_climbs_the_rungs_inside_one_budget(monkeypatch):
    """The hosted reader is given what is left, and a browser that cannot
    finish in what remains is not started."""
    import urllib.error

    def refuse(request, timeout=None, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 429, "no", {}, None)

    monkeypatch.setattr(fetch.network, "urlopen", refuse)
    given = {}

    def hosted(url, endpoint="", timeout=pagereader.TIMEOUT):
        given["hosted"] = timeout
        time.sleep(0.2)
        return ""

    def local_browser(url, timeout=browser.TIMEOUT):
        given["browser"] = timeout
        return ""

    monkeypatch.setattr(pagereader, "read", hosted)
    monkeypatch.setattr(browser, "read", local_browser)

    # An 8-second reader has 16 s for a page; the hosted rung takes what
    # there is, and a browser needs `BROWSER_MIN_SECONDS` of what is left.
    assert fetch._download("https://a.test/x", timeout=8.0) == ""
    assert 0 < given["hosted"] <= 16.0
    assert given["browser"] <= 16.0

    given.clear()
    assert fetch._download("https://a.test/x", timeout=2.0) == ""
    assert given["hosted"] <= 4.0
    assert "browser" not in given, "a 4 s budget cannot hold a browser"
