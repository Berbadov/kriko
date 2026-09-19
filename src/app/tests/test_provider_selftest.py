import json
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app import keys
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings

SECRET = "sk-test-DO-NOT-LEAK-0123456789abcdef4f2a"

CONTRACT = {
    "provider",
    "ok",
    "latency_ms",
    "error",
    "detail",
    "results",
    "tokens_in",
    "tokens_out",
    "tokens",
    "usd",
    "llm",
}


class Reply:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    for name in (
        "EXA_API_KEY",
        "TAVILY_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "EXA_BASE_URL",
        "TAVILY_BASE_URL",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    return tmp_path


def make_client(tmp_path):
    settings = Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    )
    return TestClient(create_app(settings)), settings


def serve(monkeypatch, behaviour):
    def fake(request, timeout=None):
        return behaviour(request)

    monkeypatch.setattr(urllib.request, "urlopen", fake)


def with_key(monkeypatch, provider):
    if provider == "exa":
        monkeypatch.setenv("EXA_API_KEY", SECRET)
    elif provider == "tavily":
        monkeypatch.setenv("TAVILY_API_KEY", SECRET)
    elif provider == "openai":
        monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    elif provider == "anthropic":
        monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test-1")


def search_hit():
    return Reply(json.dumps({"results": [{"url": "https://example.test/one", "title": "One"}]}).encode())


def openai_hit():
    return Reply(
        json.dumps(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            }
        ).encode()
    )


def anthropic_hit():
    return Reply(
        json.dumps(
            {
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 4, "output_tokens": 2},
            }
        ).encode()
    )


def refused():
    raise urllib.error.HTTPError("https://provider.test/search", 401, "Unauthorized", {}, None)


def silent():
    raise TimeoutError("timed out")


def garbage():
    return Reply(b"not json at all {{{")


def empty_for(provider):
    if provider in ("exa", "tavily"):
        return Reply(json.dumps({"results": []}).encode())
    if provider == "anthropic":
        return Reply(json.dumps({"content": []}).encode())
    return Reply(json.dumps({"choices": []}).encode())


def hit_for(provider):
    if provider in ("exa", "tavily"):
        return search_hit()
    if provider == "anthropic":
        return anthropic_hit()
    return openai_hit()


def test_exa_success_reports_ok_with_latency_and_result_count(isolated, monkeypatch):
    with_key(monkeypatch, "exa")
    serve(monkeypatch, lambda request: search_hit())
    client, _ = make_client(isolated)
    response = client.post("/api/keys/test", json={"provider": "exa"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT
    assert body["provider"] == "exa"
    assert body["ok"] is True
    assert body["error"] == ""
    assert body["results"] == 1
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0
    assert SECRET not in response.text


def test_tavily_success_reports_ok(isolated, monkeypatch):
    with_key(monkeypatch, "tavily")
    serve(monkeypatch, lambda request: search_hit())
    client, _ = make_client(isolated)
    body = client.post("/api/keys/test", json={"provider": "tavily"}).json()
    assert body["ok"] is True
    assert body["results"] == 1
    assert body["error"] == ""


def test_openai_success_counts_tokens(isolated, monkeypatch):
    with_key(monkeypatch, "openai")
    serve(monkeypatch, lambda request: openai_hit())
    client, _ = make_client(isolated)
    body = client.post("/api/keys/test", json={"provider": "openai"}).json()
    assert body["ok"] is True
    assert body["tokens"] == 8
    assert body["tokens_in"] == 5
    assert body["tokens_out"] == 3
    assert body["llm"] != ""


def test_anthropic_success_counts_tokens(isolated, monkeypatch):
    with_key(monkeypatch, "anthropic")
    serve(monkeypatch, lambda request: anthropic_hit())
    client, _ = make_client(isolated)
    body = client.post("/api/keys/test", json={"provider": "anthropic"}).json()
    assert body["ok"] is True
    assert body["tokens"] == 6
    assert body["llm"] == "claude-test-1"


@pytest.mark.parametrize("provider", ["exa", "tavily", "openai", "anthropic"])
def test_a_refused_key_surfaces_as_unauthorized(isolated, monkeypatch, provider):
    with_key(monkeypatch, provider)
    serve(monkeypatch, lambda request: refused())
    client, _ = make_client(isolated)
    response = client.post("/api/keys/test", json={"provider": provider})
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "unauthorized"
    assert "401" in body["detail"]
    assert SECRET not in response.text


@pytest.mark.parametrize("provider", ["exa", "tavily", "openai", "anthropic"])
def test_a_silent_provider_surfaces_as_timeout(isolated, monkeypatch, provider):
    with_key(monkeypatch, provider)
    serve(monkeypatch, lambda request: silent())
    client, _ = make_client(isolated)
    body = client.post("/api/keys/test", json={"provider": provider}).json()
    assert body["ok"] is False
    assert body["error"] == "timeout"


@pytest.mark.parametrize("provider", ["exa", "tavily", "openai", "anthropic"])
def test_a_garbage_reply_surfaces_as_malformed(isolated, monkeypatch, provider):
    with_key(monkeypatch, provider)
    serve(monkeypatch, lambda request: garbage())
    client, _ = make_client(isolated)
    body = client.post("/api/keys/test", json={"provider": provider}).json()
    assert body["ok"] is False
    assert body["error"] == "malformed"


@pytest.mark.parametrize("provider", ["exa", "tavily", "openai", "anthropic"])
def test_an_empty_reply_surfaces_as_empty(isolated, monkeypatch, provider):
    with_key(monkeypatch, provider)
    serve(monkeypatch, lambda request: empty_for(provider))
    client, _ = make_client(isolated)
    body = client.post("/api/keys/test", json={"provider": provider}).json()
    assert body["ok"] is False
    assert body["error"] == "empty"


@pytest.mark.parametrize("provider", ["exa", "tavily", "openai", "anthropic"])
def test_a_missing_key_reports_missing_key_without_touching_the_network(
    isolated, monkeypatch, provider
):
    if provider == "anthropic":
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test-1")
    calls = []
    serve(monkeypatch, lambda request: calls.append(request) or search_hit())
    client, _ = make_client(isolated)
    body = client.post("/api/keys/test", json={"provider": provider}).json()
    assert body["ok"] is False
    assert body["error"] == "missing_key"
    assert calls == []


def test_an_unknown_provider_is_not_found(isolated):
    client, _ = make_client(isolated)
    assert client.post("/api/keys/test", json={"provider": "nope"}).status_code == 404


def test_no_test_body_returns_a_key(isolated, monkeypatch):
    for provider in ("exa", "tavily", "openai", "anthropic"):
        with_key(monkeypatch, provider)
    bodies = []
    client, _ = make_client(isolated)
    serve(monkeypatch, lambda request: search_hit())
    bodies.append(client.post("/api/keys/test", json={"provider": "exa"}))
    serve(monkeypatch, lambda request: openai_hit())
    bodies.append(client.post("/api/keys/test", json={"provider": "openai"}))
    serve(monkeypatch, lambda request: refused())
    bodies.append(client.post("/api/keys/test", json={"provider": "tavily"}))
    serve(monkeypatch, lambda request: garbage())
    bodies.append(client.post("/api/keys/test", json={"provider": "openai"}))
    serve(monkeypatch, lambda request: empty_for("exa"))
    bodies.append(client.post("/api/keys/test", json={"provider": "exa"}))
    for response in bodies:
        assert SECRET not in response.text


def test_a_successful_check_leaves_a_counted_operation_row(isolated, monkeypatch):
    with_key(monkeypatch, "exa")
    serve(monkeypatch, lambda request: search_hit())
    client, settings = make_client(isolated)
    client.post("/api/keys/test", json={"provider": "exa"})
    conn = state.connect(settings.app_state_path)
    try:
        rows = state.operations(conn)
    finally:
        conn.close()
    assert rows
    assert rows[0]["name"] == "key_test"
    assert rows[0]["door"] == "app"
    assert rows[0]["state"] == "ok"


def test_a_completion_check_records_the_tokens_it_counted(isolated, monkeypatch):
    with_key(monkeypatch, "openai")
    serve(monkeypatch, lambda request: openai_hit())
    client, settings = make_client(isolated)
    client.post("/api/keys/test", json={"provider": "openai"})
    conn = state.connect(settings.app_state_path)
    try:
        rows = state.operations(conn)
    finally:
        conn.close()
    assert rows[0]["tokens"] == 8


def test_anthropic_without_a_chosen_llm_reports_no_model(isolated, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    calls = []
    serve(monkeypatch, lambda request: calls.append(request) or anthropic_hit())
    client, _ = make_client(isolated)
    body = client.post("/api/keys/test", json={"provider": "anthropic"}).json()
    assert body["ok"] is False
    assert body["error"] == "no_model"
    assert calls == []
