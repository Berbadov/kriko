"""A busy vendor gets a second attempt; a slow one does not.

`_MEANING` has told the reader "try again" for 429/500/502/503/504 since it was
written, and nothing tried again: one transient status removed a document or a
query from a paid run, and the only trace was a log line. The tests below pin
both halves of the policy, including the deliberate asymmetry — a *timeout* is
not retried, because the first attempt already spent the whole budget and the
provider is slow rather than busy.
"""

import io
import urllib.error

import pytest

from app.providers import _http


class _Reply:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError(
        "https://api.example.test/v1/x", code, "err", headers, io.BytesIO(b""))


@pytest.fixture
def sleeps(monkeypatch):
    """`time.sleep`, recorded instead of taken."""
    recorded: list[float] = []
    monkeypatch.setattr(_http.time, "sleep", recorded.append)
    return recorded


def _script(monkeypatch, outcomes):
    """Make `network.urlopen` return/raise each outcome in turn."""
    calls: list[int] = []
    queue = list(outcomes)

    def fake(url, data=None, timeout=None, **kw):
        calls.append(1)
        outcome = queue.pop(0) if queue else outcomes[-1]
        if isinstance(outcome, Exception):
            raise outcome
        return _Reply(outcome)

    monkeypatch.setattr(_http.network, "urlopen", fake)
    return calls


def test_a_busy_vendor_is_tried_again(monkeypatch, sleeps):
    calls = _script(monkeypatch, [_http_error(503), _http_error(503),
                                  b'{"ok": true}'])
    payload, why = _http.post_json_or_why("https://api.example.test/v1/x", {}, {})
    assert payload == {"ok": True}
    assert why == ""
    assert len(calls) == 3
    assert sleeps == [_http.RETRY_BACKOFF, _http.RETRY_BACKOFF * 2]


def test_a_permanent_refusal_is_not_retried(monkeypatch, sleeps):
    calls = _script(monkeypatch, [_http_error(401)])
    payload, why = _http.post_json_or_why("https://api.example.test/v1/x", {}, {})
    assert payload == {}
    assert "key was refused" in why
    assert len(calls) == 1
    assert sleeps == []


def test_a_timeout_is_not_retried(monkeypatch, sleeps):
    """The first attempt already spent the whole budget."""
    calls = _script(monkeypatch, [TimeoutError("timed out")])
    payload, why = _http.post_json_or_why("https://api.example.test/v1/x", {}, {})
    assert payload == {}
    assert "did not answer within" in why
    assert len(calls) == 1
    assert sleeps == []


def test_a_refused_connection_is_tried_again(monkeypatch, sleeps):
    """DNS and connection failures fail in milliseconds and are usually blips."""
    refused = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    calls = _script(monkeypatch, [refused, b'{"ok": 1}'])
    payload, why = _http.post_json_or_why("https://api.example.test/v1/x", {}, {})
    assert payload == {"ok": 1}
    assert why == ""
    assert len(calls) == 2


def test_the_vendors_own_retry_after_is_used(monkeypatch, sleeps):
    calls = _script(monkeypatch, [_http_error(429, retry_after="2"), b'{"ok": 1}'])
    payload, _why = _http.post_json_or_why("https://api.example.test/v1/x", {}, {})
    assert payload == {"ok": 1}
    assert sleeps == [2.0]
    assert len(calls) == 2


def test_an_absurd_retry_after_is_capped(monkeypatch, sleeps):
    _script(monkeypatch, [_http_error(503, retry_after="86400"), b'{"ok": 1}'])
    _http.post_json_or_why("https://api.example.test/v1/x", {}, {})
    assert sleeps == [_http.RETRY_AFTER_CAP]


def test_the_reason_returned_is_the_last_attempts(monkeypatch, sleeps):
    """A run that ends in a 503 must say 503, not the first transient blip."""
    _script(monkeypatch, [_http_error(429), _http_error(429), _http_error(503)])
    payload, why = _http.post_json_or_why("https://api.example.test/v1/x", {}, {})
    assert payload == {}
    assert "503" in why


def test_the_plain_helper_still_returns_an_empty_dict(monkeypatch, sleeps):
    _script(monkeypatch, [_http_error(500)])
    assert _http.post_json("https://api.example.test/v1/x", {}, {}) == {}
