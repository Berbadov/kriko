"""The browser rung: the last resort of the fetch ladder.

The plain fetch is refused, the hosted readers are refused, and the page is
still worth one more attempt, because the one client a bot challenge cannot
refuse is a real browser. This module drives the reader's own Chrome or
Edge headlessly, and the tests pin the contract the ladder depends on: a
machine with no browser reads exactly as before, a browser that fails is
an unread page, never a half-read one, and the profile it runs under is
thrown away with the run.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.providers import browser, fetch


class Page:
    """One loopback server standing in for the refused site."""

    def __init__(self, status=403):
        self.status = status
        page = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(page.status)
                body = b"<html><body>the page</body></html>"
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/x"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def page():
    one = Page()
    yield one
    one.close()


class FakeBrowser:
    """A stand-in executable that prints a DOM and records its arguments."""

    def __init__(self, tmp_path, dom="<html><body>browser words</body></html>",
                 exit_code=0, hang=False):
        self.calls = []
        self.dom = dom
        self.exit_code = exit_code
        self.hang = hang
        path = tmp_path / "browser.sh"
        path.write_text("#!/bin/sh\necho '" + dom + "'\nexit " + str(exit_code) + "\n")
        path.chmod(0o755)
        self.path = str(path)


def _wire(monkeypatch, fake):
    monkeypatch.setattr(browser, "locate", lambda: fake.path)
    monkeypatch.setattr(browser, "_switches", lambda profile: ["--dump-dom"])


def test_a_refused_page_the_readers_miss_is_read_by_the_browser(page, tmp_path,
                                                                monkeypatch):
    from app.providers import pagereader

    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr(pagereader, "PARALLEL_ENDPOINT", "http://127.0.0.1:1/mcp")
    fake = FakeBrowser(tmp_path, dom="<html><body>browser words</body></html>")
    _wire(monkeypatch, fake)
    assert "browser words" in fetch.reader()(page.url).text


def test_a_machine_with_no_browser_reads_exactly_as_before(page, monkeypatch):
    monkeypatch.setattr(browser, "locate", lambda: "")
    assert fetch.reader()(page.url).text == ""


def test_a_browser_that_fails_leaves_the_page_unread(page, tmp_path, monkeypatch):
    from app.providers import pagereader

    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr(pagereader, "PARALLEL_ENDPOINT", "http://127.0.0.1:1/mcp")
    fake = FakeBrowser(tmp_path, exit_code=1, dom="")
    _wire(monkeypatch, fake)
    assert fetch.reader()(page.url).text == ""


def test_locate_finds_a_named_browser_first(monkeypatch, tmp_path):
    fake = FakeBrowser(tmp_path)
    monkeypatch.setattr(browser, "_CACHE", {})
    monkeypatch.setenv(browser.BROWSER_ENV, fake.path)
    assert browser.locate() == fake.path


def test_locate_with_no_browser_anywhere_is_empty(monkeypatch):
    monkeypatch.setattr(browser, "_CACHE", {})
    monkeypatch.delenv(browser.BROWSER_ENV, raising=False)
    monkeypatch.setattr(browser, "_UNIX_NAMES", ())
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert browser.locate() == ""


def test_a_non_http_url_is_never_given_to_the_browser(monkeypatch):
    monkeypatch.setattr(browser, "locate", lambda: "/bin/true")
    assert browser.read("file:///etc/passwd") == ""


def test_the_dumped_dom_becomes_prose_like_any_page(tmp_path, monkeypatch):
    fake = FakeBrowser(tmp_path, dom="<html><body><p>one</p><p>two</p></body></html>")
    _wire(monkeypatch, fake)
    assert "one" in fetch.to_text(browser.read("https://a.test/x"))
