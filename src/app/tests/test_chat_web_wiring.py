"""Chat reuses configured search, respects agent tool capabilities, and streams prose."""

from email.message import Message
import threading
from types import SimpleNamespace

from app import chatdata, chatweb
from app import prefs
from app.web import state, tasks
from app.providers import network


class Hooks:
    def check(self):
        pass


class PageResponse:
    def __init__(self, status=200, body=b"<html><body>Manual says RN17.</body></html>",
                 location=""):
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"
        if location:
            self.headers["Location"] = location
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        pass

    def getcode(self):
        return self.status

    def read(self, limit):
        return self.body[:limit]


def test_local_token_stream_is_accumulated_into_complete_chat_drafts():
    class Socket:
        def stream(self, prompt, on_text):
            for piece in ["Hello", " there", "."]:
                on_text(piece)
            return "Hello there."

    drafts = []
    assert tasks._stream_chat_completion(Socket(), "hello", drafts.append) == "Hello there."
    assert drafts == ["Hello", "Hello there", "Hello there."]


def test_free_chat_search_uses_saved_address_language_and_bounded_sockets(tmp_path, monkeypatch):
    from app import chatweb
    from app.providers import openserp

    conn = state.connect(tmp_path / "app.sqlite")
    try:
        prefs.write(conn, {prefs.LOCAL_SEARCH_URL: "http://127.0.0.1:7111",
                           prefs.LOCAL_SEARCH_LANGUAGE: "tr"})
        seen = {}

        def searcher(base, **kwargs):
            seen.update(base=base, **kwargs)
            return lambda query, limit: [{"url": "https://example.org", "title": query}]

        monkeypatch.setattr(openserp, "searcher", searcher)
        monkeypatch.setattr(chatweb, "reader", lambda **kwargs: seen.update(read=kwargs) or (lambda url: "text"))
        hooks = Hooks()
        search, read = tasks._chat_web_sources(conn, tmp_path / "app.sqlite", hooks)
        assert seen == {"base": "http://127.0.0.1:7111", "engine": "duckduckgo,bing,google",
                        "language": "tr", "timeout": 8.0, "mode": "any",
                        "read": {"timeout": 5.0}}
        assert search.check_cancelled == hooks.check
        assert search("a product", 3)[0]["title"] == "a product"
        assert read("https://example.org") == "text"
    finally:
        conn.close()


def test_chat_honours_an_explicit_hosted_search_choice(tmp_path, monkeypatch):
    from app import providers

    conn = state.connect(tmp_path / "app.sqlite")
    try:
        prefs.write(conn, {prefs.SEARCH: "tavily"})
        seen = []

        def selected(path, preferred):
            seen.append((path, preferred))
            return (lambda query, limit: []), "tavily"

        monkeypatch.setattr(providers, "_searcher", selected)
        tasks._chat_web_sources(conn, tmp_path / "app.sqlite", Hooks())
        assert seen == [(tmp_path / "app.sqlite", "tavily")]
    finally:
        conn.close()


def test_chat_builds_its_host_search_and_reader_once_per_turn(monkeypatch):
    created_searchers = []
    created_readers = []
    host_readers = []
    searches = []
    reads = []
    progress = Hooks()

    def build_searcher(app_state, path, actual_progress):
        created_searchers.append((app_state, path, actual_progress))
        def search(query, limit):
            searches.append((query, limit))
            return []

        return search

    def build_reader(*, timeout):
        created_readers.append((threading.get_ident(), timeout))

        def read(url):
            reads.append(url)
            return "page text"

        host_readers.append(read)
        return read

    monkeypatch.setattr(tasks, "_chat_web_searcher", build_searcher)
    monkeypatch.setattr(chatweb, "reader", build_reader)
    search, read = tasks._chat_web_accessors("app", "state.sqlite", progress)
    owner = threading.get_ident()
    assert created_readers == [(owner, 5.0)]
    assert created_searchers == []

    def checker():
        pass

    read.check_cancelled = checker

    assert search("first", 5) == []
    assert read("https://example.org/page") == "page text"
    assert search("second", 2) == []
    assert created_searchers == [("app", "state.sqlite", progress)]
    assert searches == [("first", 5), ("second", 2)]
    assert reads == ["https://example.org/page"]
    assert host_readers[0].check_cancelled is checker


def test_direct_url_reads_use_the_real_chat_reader_on_a_worker(tmp_path, monkeypatch):
    conn = state.connect(tmp_path / "app.sqlite")
    owner = threading.get_ident()
    factory_threads = []
    request_threads = []
    checker_threads = []
    searcher_threads = []
    real_reader = chatweb.reader

    def tracked_reader(*, timeout):
        factory_threads.append(threading.get_ident())
        return real_reader(timeout=timeout)

    def forbidden_searcher(*_args):
        searcher_threads.append(threading.get_ident())
        raise AssertionError("a reader-provided URL should skip search")

    def open_url(url, *, timeout, check, opener):
        request_threads.append(threading.get_ident())
        checker_threads.append(threading.get_ident())
        check()
        return PageResponse()

    monkeypatch.setattr(chatweb, "reader", tracked_reader)
    monkeypatch.setattr(tasks, "_chat_web_searcher", forbidden_searcher)
    monkeypatch.setattr(network, "urlopen", open_url)
    search, read = tasks._chat_web_accessors(conn, tmp_path / "app.sqlite", Hooks())
    assert factory_threads == [owner]

    def owner_check():
        assert threading.get_ident() == owner

    ctx = chatdata.Context(app=conn, web_search=search, web_read=read,
                           check_cancelled=owner_check)
    try:
        out = chatdata.run("web_search", ctx,
                           {"query": "Summarize https://93.184.216.34/manual"})
    finally:
        conn.close()

    assert out["rows"][0]["page_read"] is True
    assert "RN17" in out["rows"][0]["page_excerpt"]
    assert searcher_threads == []
    assert request_threads and all(thread != owner for thread in request_threads)
    assert checker_threads == request_threads


def test_direct_url_deadline_reaches_the_underlying_reader_between_redirects(
        tmp_path, monkeypatch):
    conn = state.connect(tmp_path / "app.sqlite")
    started = threading.Event()
    release = threading.Event()
    cancellation_checked = threading.Event()
    requests = []

    class ReaderEvent:
        def __init__(self):
            self.cancelled = False

        def set(self):
            self.cancelled = True

        def is_set(self):
            if self.cancelled:
                cancellation_checked.set()
            return self.cancelled

    monkeypatch.setattr(chatdata, "threading", SimpleNamespace(Event=ReaderEvent))
    monkeypatch.setattr(chatdata, "WEB_READ_DEADLINE_SECONDS", 0.2)
    monkeypatch.setattr(
        network, "urlopen",
        lambda url, **kwargs: (
            requests.append(url), started.set(), release.wait(1.0),
            PageResponse(status=302, location="https://93.184.216.34/next"),
        )[-1],
    )
    search, read = tasks._chat_web_accessors(conn, tmp_path / "app.sqlite", Hooks())
    ctx = chatdata.Context(app=conn, web_search=search, web_read=read)
    try:
        out = chatdata.run("web_search", ctx,
                           {"query": "Summarize https://93.184.216.34/manual"})
        assert started.is_set()
        assert out["rows"][0]["page_read"] is False
        release.set()
        assert cancellation_checked.wait(1.0)
        assert requests == ["https://93.184.216.34/manual"]
    finally:
        release.set()
        conn.close()


def test_chat_native_tools_follow_web_intent_without_slowing_direct_or_local_turns():
    assert tasks._chat_native_tools("Find today's price for a desk lamp", []) is True
    assert tasks._chat_native_tools("What is a closure?", []) is None
    assert tasks._chat_native_tools("What is in my saved checks?", []) is None


def test_unset_chat_tool_policy_respects_each_harness_capability(monkeypatch, tmp_path):
    class Progress:
        def __init__(self):
            self.logs = []

        def check(self):
            pass

        def log(self, line):
            self.logs.append(line)

        def set(self, _progress, _message):
            pass

    class Researcher:
        def __init__(self, protocol, transport_mode="auto"):
            self.harness = SimpleNamespace(protocol=protocol)
            self.telemetry = {}
            self.transport_mode = transport_mode
            self.transport_seen = None
            self.allow_tools = None

        def ask(self, _brief, *, allow_tools=True):
            self.allow_tools = allow_tools
            self.transport_seen = self.transport_mode
            self.telemetry["run"] = {"transport": "process"}
            return "Answer."

    monkeypatch.setattr(tasks, "_use_local_ask", lambda *_args: False)
    monkeypatch.setattr(tasks, "_cap_agent", lambda *_args: None)
    monkeypatch.setattr(tasks, "_wire_researcher_text", lambda *_args: None)
    monkeypatch.setattr(tasks, "_apply_source_options", lambda *_args: None)
    monkeypatch.setattr("app.providers.agent_ready", lambda *_args: True)

    def run(protocol, allow_tools, transport_mode="auto"):
        researcher = Researcher(protocol, transport_mode)
        identities = []
        progress = Progress()
        monkeypatch.setattr("app.providers.harness_researcher",
                            lambda **_kwargs: researcher)
        answer, _ = tasks._ask_about_checks(
            SimpleNamespace(app_state_path=tmp_path / "state.sqlite"),
            {"backend": "harness", "harness": "chosen"}, progress, "brief",
            allow_tools=allow_tools, on_agent=identities.append)
        return (answer, researcher.allow_tools, identities, researcher.transport_seen,
                researcher.transport_mode, progress.logs)

    # These headless CLIs have a verified no-tool persistent answer path.
    answer, enabled, identity, _seen, _after, _logs = run("codex", None)
    assert answer == "Answer."
    assert enabled is False
    assert identity[-1]["transport"] == "process"

    # Other CLIs have no verified no-tool mode and retain their native tools.
    answer, enabled, identity, _seen, _after, _logs = run("claude", None)
    assert answer == "Answer."
    assert enabled is True
    assert identity[-1]["transport"] == "process"

    # An obvious web turn explicitly opts into native tools on any harness.
    answer, enabled, _identity, _seen, _after, _logs = run("antigravity", True)
    assert answer == "Answer."
    assert enabled is True

    # A web turn can select a tool-capable request locally when the general
    # preference asks Codex for persistent, tool-less completion.
    answer, enabled, _identity, seen, after, logs = run("codex", True, "persistent")
    assert answer == "Answer."
    assert enabled is True
    assert seen == "auto"
    assert after == "persistent"
    assert any("tool-enabled path" in line for line in logs)
