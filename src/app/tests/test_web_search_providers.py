"""The web search providers: DeepSeek's adapter, the order, and the health shown in Settings (#270, #267).

The reader's words (#267): "web search provider selection". Done when the
engine lists the providers it supports, says which need a key and whether one
is saved, tries one on request and shows what came back, and keeps an order of
fallback; and (#270) shows when each last answered and how often it has not.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import keys, prefs, sharekeys
from app.providers import MissingKey, deepseek, openserp, websearch
from app.providers._http import SearchFailed
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.research.politeness import LocalSearchError

SECRET = "sk-ds-do-not-leak-9876543210"


@pytest.fixture(autouse=True)
def isolated_keys(monkeypatch, tmp_path):
    for provider in keys.PROVIDERS:
        monkeypatch.delenv(provider.env, raising=False)
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")


@pytest.fixture
def service(monkeypatch):
    """A DeepSeek stand-in whose next answer the test chooses."""
    seen: list[dict] = []
    reply = {"status": 200, "body": {"results": [
        {"url": "https://a.example/x", "title": "A", "snippet": "s"}]}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"),
                         "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            payload = json.dumps(reply["body"]).encode()
            self.send_response(reply["status"])
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.05
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setattr("app.providers._http.RETRY_BACKOFF", 0.0)
    yield type("Service", (), {"seen": seen, "reply": reply})
    server.shutdown()
    server.server_close()


def test_the_adapter_speaks_the_benchmarks_request_and_returns_the_common_hit(monkeypatch, service):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    search = deepseek.searcher()
    assert search("heater that trips the breaker", 3) == [
        {"url": "https://a.example/x", "title": "A", "site": "a.example", "snippet": "s"}]
    assert service.seen == [{"path": "/v1/tools/search", "auth": f"Bearer {SECRET}",
                             "body": {"query": "heater that trips the breaker", "count": 3,
                                      "need_content": False}}]


def test_a_query_over_the_services_limit_is_cut_at_a_word_not_refused(monkeypatch, service):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    long = " ".join(["rattling"] * 40)
    deepseek.searcher()(long, 2)
    sent = service.seen[0]["body"]["query"]
    assert len(sent) <= deepseek.MAX_QUERY_CHARS and not sent.endswith(" ")
    assert set(sent.split()) == {"rattling"}


def test_a_refused_key_is_a_named_failure_without_the_key(monkeypatch, service):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    service.reply.update(status=401, body={"error": f"bad key {SECRET}"})
    with pytest.raises(SearchFailed) as caught:
        deepseek.searcher()("q", 3)
    assert "401" in str(caught.value) and SECRET not in str(caught.value)


def test_no_key_is_missing_key_not_a_request():
    with pytest.raises(MissingKey):
        deepseek.searcher()


def test_the_cancel_hook_is_honoured_before_any_request(monkeypatch, service):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    search = deepseek.searcher()

    class Stopped(Exception):
        cancelled = True

    def stop():
        raise Stopped

    search.check_cancelled = stop
    with pytest.raises(Stopped):
        search("q", 3)
    assert service.seen == []


# ── the order ────────────────────────────────────────────────────────────

def test_automatic_leads_with_deepseek_once_it_can_be_asked_and_never_adds_openserp(monkeypatch):
    assert websearch.order({})["effective"] == ["openserp"]
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    plan = websearch.order({})
    assert plan["primary"] == "deepseek" and plan["automatic"]
    assert plan["effective"] == ["deepseek"]
    # The reader's own choice of OpenSERP still keeps DeepSeek behind it.
    assert websearch.order({prefs.SEARCH: "openserp"})["effective"] == ["openserp", "deepseek"]


def test_shared_deepseek_grant_is_used_after_openserp_fails(
        monkeypatch, tmp_path, service):
    """A shared grant in this app home enables automatic fallback and execution."""
    home = tmp_path / "friend"
    home.mkdir()
    app_state_path = home / "app.sqlite"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    grant_key = "sk-shared-deepseek-secret-987654321"
    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "web-search-test-pepper")
    access = sharekeys.make_access("a long test password", {"deepseek": grant_key})
    sharekeys.unlock(access, "a long test password", where=home)

    # The shared access makes DeepSeek the default; OpenSERP is only asked when chosen.
    assert websearch.order({}, app_state_path)["effective"] == ["deepseek"]
    assert websearch.order({prefs.SEARCH: "openserp"}, app_state_path)["effective"] == [
        "openserp", "deepseek"]
    assert websearch.order(
        {prefs.SEARCH: "openserp", prefs.SEARCH_FALLBACK: "none"}, app_state_path)["effective"] == [
        "openserp"]
    conn = state.connect(app_state_path)
    try:
        rows = {row["id"]: row for row in websearch.status(conn)["providers"]}
    finally:
        conn.close()
    assert rows["deepseek"]["key_saved"] and rows["deepseek"]["ready"]
    logged = []

    def down(_chosen):
        def search(*_args, **_kwargs):
            raise LocalSearchError("OpenSERP is down")
        return search

    chain = websearch.build({prefs.SEARCH: "openserp"}, app_state_path, log=logged.append,
                            openserp_factory=down)
    assert chain("sata ssd", 3) == [
        {"url": "https://a.example/x", "title": "A", "site": "a.example", "snippet": "s"}
    ]
    assert chain.providers == ["openserp", "deepseek"]
    assert [attempt["provider"] for attempt in chain.attempts] == ["openserp", "deepseek"]
    assert service.seen[0]["auth"] == f"Bearer {grant_key}"
    assert grant_key not in "\n".join(logged)
    assert grant_key not in json.dumps(chain.attempts)
    assert grant_key not in (home / "shared.json").read_text(encoding="utf-8")


def test_last_reserved_trial_question_can_build_lazy_search_after_clarify(
        monkeypatch, tmp_path, service):
    home = tmp_path / "trial-friend"
    home.mkdir()
    app_state_path = home / "app.sqlite"
    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "web-search-trial-test-pepper")
    monkeypatch.setattr(sharekeys, "TRIAL_FILE", tmp_path / "trial_access.json")
    sharekeys.write_trial(
        sharekeys.make_trial({"deepseek": SECRET}, questions=1),
        where=sharekeys.TRIAL_FILE)
    # Clarification reserved the final allowance before host search is built.
    reservation = "last-question-job-id"
    assert sharekeys.charge(home, reservation_id=reservation) == 0
    assert not sharekeys.allowance(home)["available"]
    assert not websearch.has_key("deepseek", app_state_path)
    assert not websearch.has_key(
        "deepseek", app_state_path, trial_reservation_id="new-question")
    assert websearch.order({}, app_state_path)["effective"] == ["openserp"]
    with pytest.raises(MissingKey):
        deepseek.searcher(shared_home=home)

    def down(_chosen):
        def search(*_args, **_kwargs):
            raise LocalSearchError("OpenSERP is down")
        return search

    logged = []
    assert websearch.build(
        {}, app_state_path, openserp_factory=down,
        trial_reservation_id=reservation).providers == ["deepseek"]
    chain = websearch.build(
        {prefs.SEARCH: "openserp"}, app_state_path, openserp_factory=down, log=logged.append,
        trial_reservation_id=reservation)
    assert chain.providers == ["openserp", "deepseek"]
    assert chain("sata ssd", 3)[0]["url"] == "https://a.example/x"
    assert service.seen[0]["auth"] == f"Bearer {SECRET}"
    assert sharekeys.allowance(home)["used"] == 1
    conn = state.connect(app_state_path)
    try:
        assert websearch.probe(
            conn, app_state_path, "deepseek", trial_reservation_id=reservation)["ok"]
        assert not websearch.probe(conn, app_state_path, "deepseek")["ok"]
    finally:
        conn.close()
    assert len(service.seen) == 2
    assert SECRET not in json.dumps(chain.attempts) + json.dumps(logged)


def test_no_hosted_provider_is_asked_unless_the_reader_put_it_in_the_order(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa-key-1234567")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key-1234567")
    assert websearch.order({})["effective"] == ["openserp"]
    chosen = {prefs.SEARCH_FALLBACK: "tavily,exa,tavily,nonsense"}
    plan = websearch.order(chosen)
    assert plan["fallback"] == ["tavily", "exa"] and plan["effective"] == ["openserp", "tavily", "exa"]


def test_none_means_nothing_behind_the_first_choice(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    plan = websearch.order({prefs.SEARCH: "openserp", prefs.SEARCH_FALLBACK: "none"})
    assert plan["effective"] == ["openserp"] and not plan["automatic"]


def test_a_fallback_without_its_key_is_skipped_not_an_error():
    plan = websearch.order({prefs.SEARCH_FALLBACK: "deepseek,exa"})
    assert plan["fallback"] == ["deepseek", "exa"] and plan["effective"] == ["openserp"]


def test_the_first_choice_is_never_also_its_own_fallback(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    plan = websearch.order({prefs.SEARCH: "deepseek", prefs.SEARCH_FALLBACK: "deepseek,openserp"})
    assert plan["effective"] == ["deepseek", "openserp"]


# ── health and the screen's document ─────────────────────────────────────

def _client(tmp_path):
    return TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl")))


def test_health_counts_ok_empty_and_error_and_survives_a_restart(tmp_path):
    path = tmp_path / "app.sqlite"
    for outcome in ("ok", "error", "empty", "ok"):
        websearch.record(path, "openserp", outcome, "the SERP answered with a challenge page")
    conn = state.connect(path)
    try:
        row = websearch.health(conn)["openserp"]
    finally:
        conn.close()
    assert row["calls"] == 4 and row["recent"] == 4
    assert row["miss_rate"] == 0.5
    assert row["last_success"] and row["last_failure"]
    assert "challenge page" in row["last_problem"]


def test_recording_never_raises_into_a_search(tmp_path):
    websearch.record(tmp_path / "missing" / "dir" / "app.sqlite", "openserp", "ok")
    websearch.record(None, "openserp", "ok")


def test_the_screens_document_lists_every_provider_with_its_key_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    body = _client(tmp_path).get("/api/search-providers").json()
    rows = {row["id"]: row for row in body["providers"]}
    assert list(rows) == ["openserp", "deepseek", "exa", "tavily"]
    assert rows["openserp"]["needs_key"] is False and rows["openserp"]["key_saved"] is None
    assert rows["deepseek"]["needs_key"] and rows["deepseek"]["key_saved"] is True
    assert rows["exa"]["key_saved"] is False and rows["exa"]["ready"] is False
    assert body["effective"] == ["deepseek"] and body["primary"] == "deepseek" and body["automatic"] is True
    assert SECRET not in json.dumps(body)


def test_testing_a_provider_runs_one_query_and_shows_what_came_back(tmp_path, monkeypatch, service):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET)
    client = _client(tmp_path)
    shown = client.post("/api/search-providers/test", json={"provider": "deepseek", "query": "x y"}).json()
    assert shown["ok"] and shown["results"] == [{"title": "A", "url": "https://a.example/x", "site": "a.example"}]
    assert len(service.seen) == 1
    service.reply.update(status=503, body={})
    failed = client.post("/api/search-providers/test", json={"provider": "deepseek"}).json()
    assert not failed["ok"] and "503" in failed["error"] and SECRET not in json.dumps(failed)
    health = {row["id"]: row["health"] for row in client.get("/api/search-providers").json()["providers"]}
    assert health["deepseek"]["calls"] == 2 and health["deepseek"]["miss_rate"] == 0.5


def test_testing_a_provider_without_a_key_says_so_and_spends_nothing(tmp_path, service):
    shown = _client(tmp_path).post("/api/search-providers/test", json={"provider": "exa"}).json()
    assert not shown["ok"] and "needs a key" in shown["error"]
    assert service.seen == []


def test_testing_openserp_reports_a_service_that_is_not_there(tmp_path, monkeypatch):
    def down(*_a, **_k):
        def search(*_q, **_o):
            raise LocalSearchError("connection refused")
        return search

    monkeypatch.setattr(openserp, "searcher", down)
    shown = _client(tmp_path).post("/api/search-providers/test", json={"provider": "openserp"}).json()
    assert shown["ok"] is False and "connection refused" in shown["error"]


def test_the_order_is_saved_with_the_other_settings_and_validated(tmp_path):
    client = _client(tmp_path)
    saved = client.put("/api/prefs", json={"search_provider": "deepseek",
                                          "search_fallback": "openserp, exa,openserp"})
    assert saved.status_code == 200
    assert saved.json()["chosen"]["search_fallback"] == "openserp,exa"
    assert client.put("/api/prefs", json={"search_provider": "bing"}).status_code == 422
    assert client.put("/api/prefs", json={"search_fallback": "openserp,bing"}).status_code == 422
    assert client.put("/api/prefs", json={"search_fallback": "none"}).json()["chosen"]["search_fallback"] == "none"
    body = client.get("/api/search-providers").json()
    assert body["primary"] == "deepseek" and body["fallback"] == []


def test_choosing_openserp_does_not_break_the_paid_plane_choice(tmp_path, monkeypatch):
    from app import providers

    monkeypatch.setenv("EXA_API_KEY", "exa-key-1234567")
    search, name = providers._searcher(None, "openserp")
    assert name == "exa" and callable(search)
