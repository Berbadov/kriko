"""OpenSERP is sometimes iffy, so a keyed DeepSeek search stands behind it (#270).

The reader's words: "deepseek search implementation, openserp is sometimes is
iffy."

What "iffy" looks like is already measured in `providers/openserp.py`'s own
notes: engines that answer with a challenge page, engines that time out, and an
engine that answers an empty set about half the time. The adapter reports the
first two as `LocalSearchError` and the last as `[]`. Before this, Chat took
either as the end of the search: the error escaped to the turn, the empty list
meant "the web has nothing". These tests drive the real chat searcher
(`tasks._chat_web_searcher`) against a stand-in SERP that fails the three ways,
and a stand-in DeepSeek service on a loopback socket speaking the wire shape
the product search benchmark already uses (`POST /v1/tools/search`, bearer key).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import keys, prefs
from app.providers import openserp
from app.web import jobs, state, tasks
from kriko.research.politeness import LocalSearchError

SECRET = "sk-deepseek-secret-1234567890"


class _Log:
    """The job's progress channel: lines in, cancel check out."""

    def __init__(self):
        self.lines: list[str] = []
        self.cancelled = False
        self.checks = 0

    def log(self, line):
        self.lines.append(line)

    def check(self):
        self.checks += 1
        if self.cancelled:
            raise jobs.Cancelled("stop")


@pytest.fixture
def deepseek(monkeypatch, tmp_path):
    """A DeepSeek stand-in; `calls` records each request it was sent."""
    calls: list[dict] = []
    mode = {"status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append({"path": self.path, "body": body,
                          "auth": self.headers.get("Authorization", "")})
            if mode["status"] != 200:
                self.send_response(mode["status"])
                self.end_headers()
                return
            payload = json.dumps({"results": [
                {"url": "https://forum.example/thread-1", "title": f"hit for {body['query']}",
                 "snippet": "owners report rattling"},
                {"url": "https://mag.example/review", "title": "long term test"},
                {"title": "no address, dropped"},
            ]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    # Presence is read from the key store as well as the environment: point the
    # store at an empty file so the reader's own keys never decide a test.
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    yield type("DeepSeek", (), {"calls": calls, "mode": mode})
    server.shutdown()
    server.server_close()


def _stand_in_serp(monkeypatch, behaviour):
    """OpenSERP as the reader met it: `behaviour(query)` answers, raises or is empty."""
    seen: list[str] = []

    def searcher(base="", **kwargs):
        def search(query, limit=5):
            seen.append(query)
            return behaviour(query)
        return search

    monkeypatch.setattr(openserp, "searcher", searcher)
    return seen


def _flaky(query):
    if "challenge" in query:
        raise LocalSearchError("the SERP answered with a challenge page")
    if "empty" in query:
        return []
    return [{"url": "https://serp.example/a", "title": "from openserp", "site": "serp.example"}]


def _build(tmp_path, log):
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        return tasks._chat_web_searcher(conn, tmp_path / "app.sqlite", log)
    finally:
        conn.close()


def test_a_challenged_serp_falls_back_to_deepseek_and_the_log_says_so(tmp_path, monkeypatch, deepseek):
    seen = _stand_in_serp(monkeypatch, _flaky)
    log = _Log()
    search = _build(tmp_path, log)

    hits = search("rattling challenge noise", 5)

    assert [hit["url"] for hit in hits] == ["https://forum.example/thread-1",
                                           "https://mag.example/review"]
    assert set(hits[0]) >= {"url", "title", "site"}, "the same hit shape the other providers return"
    assert hits[0]["site"] == "forum.example"
    assert seen == ["rattling challenge noise"]
    assert deepseek.calls[0]["path"] == "/v1/tools/search"
    assert deepseek.calls[0]["auth"] == f"Bearer {SECRET}"
    text = "\n".join(log.lines)
    assert "OpenSERP failed" in text and "challenge page" in text
    assert "falling back to DeepSeek" in text
    assert SECRET not in text


def test_an_empty_answer_from_the_serp_is_also_a_reason_to_fall_back(tmp_path, monkeypatch, deepseek):
    _stand_in_serp(monkeypatch, _flaky)
    log = _Log()
    hits = _build(tmp_path, log)("empty engine query", 5)
    assert hits and hits[0]["url"].startswith("https://forum.example")
    assert any("OpenSERP returned nothing" in line for line in log.lines)


def test_a_working_serp_never_spends_a_deepseek_query(tmp_path, monkeypatch, deepseek):
    _stand_in_serp(monkeypatch, _flaky)
    log = _Log()
    hits = _build(tmp_path, log)("a fine query", 5)
    assert [hit["title"] for hit in hits] == ["from openserp"]
    assert deepseek.calls == []
    # One line, and it is the search itself: which kind (none was asked for
    # here), which words, and that the answer came from one site.
    assert log.lines == ["searched: a fine query -> search returned 1 result(s) at serp.example"]


def test_without_a_deepseek_key_the_failure_is_the_same_as_before(tmp_path, monkeypatch, deepseek):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    _stand_in_serp(monkeypatch, _flaky)
    search = _build(tmp_path, _Log())
    with pytest.raises(LocalSearchError):
        search("a challenge", 5)
    assert search("empty one", 5) == []
    assert deepseek.calls == []


def test_when_both_fail_the_reader_hears_both_and_no_key_is_logged(tmp_path, monkeypatch, deepseek):
    deepseek.mode["status"] = 401
    _stand_in_serp(monkeypatch, _flaky)
    log = _Log()
    search = _build(tmp_path, log)
    with pytest.raises(LocalSearchError) as caught:
        search("a challenge", 5)
    assert "DeepSeek" in str(caught.value) and "OpenSERP" in str(caught.value)
    assert SECRET not in "\n".join(log.lines) + str(caught.value)


def test_cancelling_is_not_a_failure_to_fall_back_from(tmp_path, monkeypatch, deepseek):
    log = _Log()

    def cancelled(query):
        log.cancelled = True
        raise jobs.Cancelled("stop")

    _stand_in_serp(monkeypatch, cancelled)
    search = _build(tmp_path, log)
    with pytest.raises(jobs.Cancelled):
        search("anything", 5)
    assert deepseek.calls == []


def test_deepseek_as_the_chosen_provider_with_openserp_behind_it(tmp_path, monkeypatch, deepseek):
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        prefs.write(conn, {prefs.SEARCH: "deepseek", prefs.SEARCH_FALLBACK: "openserp"})
    finally:
        conn.close()
    seen = _stand_in_serp(monkeypatch, _flaky)
    log = _Log()
    search = _build(tmp_path, log)
    assert search("first choice", 3)[0]["url"].startswith("https://forum.example")
    assert seen == []
    deepseek.mode["status"] = 503
    monkeypatch.setattr("app.providers._http.RETRY_BACKOFF", 0.0)
    assert search("second", 3)[0]["url"] == "https://serp.example/a"
    assert any("falling back to OpenSERP" in line for line in log.lines)
