"""C1 and C2: a chosen URL must not become a way to reach this machine.

Two paths pointed at whoever supplied the URL, and both are pinned here:

* `fetch._download` reads pages that a search result or a model named. Nothing
  stopped one of those being `http://127.0.0.1:8787/...` — the sidecar's own
  API, which has no authentication because loopback was the whole argument, and
  which can install packs and open a terminal — or `169.254.169.254`, the cloud
  metadata address that hands out credentials on a rented machine
  *(C2)*;
* `GET /api/packs/updates?index_url=…` takes a URL from the request, and an
  `<img src>` fires it with no `Origin` header for the middleware to object to
  *(C1)*.

The rule is a refusal, not a warning, and the tests below assert that nothing
was even *attempted*: the strongest statement available without a network.
"""

import urllib.error

import pytest

from app import packsource
from app.providers import egress, fetch


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8787/api/health",          # the sidecar's own API
    "http://localhost:8787/api/packs",
    "http://[::1]:8787/x",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://10.0.0.5/router",
    "http://192.168.1.10:8000/",
    "http://172.16.4.4/",
    "file:///etc/passwd",
])
def test_a_url_that_reaches_this_machine_is_refused(url):
    assert egress.reason_to_refuse(url)


@pytest.mark.parametrize("url", [
    "https://example.com/article",
    "https://example.test/article",   # reserved: does not resolve, not refused
])
def test_a_public_url_is_allowed(url):
    assert egress.reason_to_refuse(url) is None


def test_the_readers_own_index_may_be_on_this_machine():
    """A local mirror is a real thing to want, and that URL is the reader's own."""
    assert egress.reason_to_refuse("http://127.0.0.1:8000/packs.json",
                                   allow_private=True) is None


def test_the_plain_fetch_never_opens_a_socket_to_this_machine(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("a request was attempted")

    monkeypatch.setattr(fetch.network, "urlopen", explode)
    assert fetch._download("http://127.0.0.1:8787/api/health", 1.0) == ""
    assert fetch._download("http://169.254.169.254/latest/meta-data/", 1.0) == ""


def test_the_browser_rung_never_starts_a_browser_for_this_machine(monkeypatch):
    def explode():
        raise AssertionError("a browser was located")

    monkeypatch.setattr("app.providers.browser.locate", explode)
    from app.providers import browser
    assert browser.read("http://127.0.0.1:8787/api/health") == ""


def test_the_pack_index_refuses_before_it_opens_a_socket():
    """`index_url` comes from the request; the refusal is a ValueError."""
    with pytest.raises(ValueError, match="will not fetch it"):
        packsource.fetch_index("http://127.0.0.1:8787/api/health")


def test_the_configured_index_is_exempt(monkeypatch):
    """The same URL is attempted (and fails on the network) when allowed."""
    def refuse(*_args, **_kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

    monkeypatch.setattr(packsource.urllib.request, "urlopen", refuse)
    with pytest.raises(urllib.error.URLError):
        packsource.fetch_index("http://127.0.0.1:9/packs.json", allow_private=True)
