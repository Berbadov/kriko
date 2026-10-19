"""The browser rung must read a real page, not deadlock on its own pipe.

`--dump-dom` prints the whole DOM. The cancellable path used to start Chrome
with `stdout=subprocess.PIPE` and then poll `process.poll()` without ever
draining that pipe, so the first page larger than the ~64 KB kernel buffer
blocked Chrome on write, `poll()` never returned, the entire timeout burned and
the rung returned `""`. `""` is also its honest answer for a page it cannot
read, so the ladder fell through and nothing anywhere said why.

The fake browser below is `sys.executable` printing 200,000 characters — well
past the buffer — which is the case that used to hang.
"""

import sys

import pytest

from app.providers import browser

BIG_DOM = "x" * 200_000

#: The DOM is built inside the child: a 200,000-character *argument* would blow
#: past Windows' 32 KB command line before the browser ever started.
PRINT_BIG_DOM = "import sys; sys.stdout.write('x' * 200000)"


def _fake_browser(monkeypatch, code: str):
    monkeypatch.setattr(browser, "locate", lambda: sys.executable)
    monkeypatch.setattr(browser, "_switches", lambda _profile: ["-c", code])


def test_a_dom_larger_than_a_pipe_buffer_is_read(monkeypatch):
    _fake_browser(monkeypatch, PRINT_BIG_DOM)
    dom = browser.read("https://listing.test/a", timeout=60, check_cancelled=lambda: None)
    assert len(dom) == len(BIG_DOM)


def test_the_same_page_reads_without_a_cancel_hook(monkeypatch):
    """`subprocess.run` drains properly; both branches must behave alike."""
    _fake_browser(monkeypatch, PRINT_BIG_DOM)
    assert len(browser.read("https://listing.test/a", timeout=60)) == len(BIG_DOM)


def test_a_cancel_stops_the_child_and_propagates(monkeypatch):
    """The kill has to take the tree, and it has to happen promptly."""
    _fake_browser(monkeypatch, "import time; time.sleep(60)")

    class Cancelled(Exception):
        pass

    def cancel():
        raise Cancelled("reader closed the panel")

    with pytest.raises(Cancelled):
        browser.read("https://listing.test/a", timeout=60, check_cancelled=cancel)


def test_a_page_that_prints_nothing_is_an_honest_empty_read(monkeypatch):
    _fake_browser(monkeypatch, "pass")
    assert browser.read("https://listing.test/a", timeout=60,
                        check_cancelled=lambda: None) == ""


def test_a_non_http_scheme_never_starts_a_browser(monkeypatch):
    def explode():
        raise AssertionError("locate() must not be reached")

    monkeypatch.setattr(browser, "locate", explode)
    assert browser.read("file:///etc/passwd", check_cancelled=lambda: None) == ""
