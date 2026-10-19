"""The custom compatible agent stays on its selected endpoint and search tools."""

import json
import pytest

from app import prefs
from app.providers import apiagent, harness, mistral
from app.web import state


def test_compatible_agent_completes_a_search_tool_loop(monkeypatch, tmp_path):
    secret = "sk-private-fixture-only"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    app_path = tmp_path / "app.sqlite"
    conn = state.connect(app_path)
    prefs.write(conn, {prefs.LLM_BASE_URL: "https://gateway.test/v1", prefs.SEARCH: "exa"})
    conn.close()
    monkeypatch.setattr("app.keys.search_providers", lambda: ["exa"])
    monkeypatch.setattr(
        "app.providers._searcher",
        lambda *args: (lambda query, limit: [{
            "url": "https://docs.test/page", "title": "Evidence", "site": "docs.test",
        }], "exa"),
    )
    monkeypatch.setattr("app.providers.fetch.reader", lambda: lambda url: "The model costs 42 credits.")
    requests = []
    responses = iter([
        ({"choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "call-1", "function": {
                "name": "web_search", "arguments": json.dumps({"query": "model credits"}),
            }}],
        }}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}}, ""),
        ({"choices": [{"message": {"content": "It costs 42 credits."}}],
          "usage": {"prompt_tokens": 20, "completion_tokens": 5}}, ""),
    ])

    def post(url, payload, headers, timeout):
        requests.append((url, payload, headers))
        return next(responses)

    monkeypatch.setattr("app.providers._http.post_json_or_why", post)
    reply = apiagent.openai_compatible_converse(
        "Find the price", model="my-model", app_state_path=app_path)

    assert reply.text == "It costs 42 credits."
    assert reply.queries == ["model credits"]
    assert reply.sources["https://docs.test/page"]["text"] == "The model costs 42 credits."
    assert reply.tokens_in == 30 and reply.tokens_out == 8
    assert reply.usage_complete is True
    assert requests[0][0] == "https://gateway.test/v1/chat/completions"
    assert requests[0][1]["model"] == "my-model"
    assert requests[0][1]["max_tokens"] == 2048
    assert requests[1][1]["messages"][-1]["content"] == json.dumps(
        {"results": [{"url": "https://docs.test/page", "title": "Evidence",
                      "content": "The model costs 42 credits."}]},
        ensure_ascii=False,
    )
    assert requests[0][2]["authorization"] == f"Bearer {secret}"
    assert secret not in repr(reply)


def test_compatible_agent_marks_missing_token_usage_incomplete(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr("app.keys.search_providers", lambda: [])
    monkeypatch.setattr(
        "app.providers._http.post_json_or_why",
        lambda *args, **kwargs: ({"choices": [{"message": {"content": "ok"}}]}, ""),
    )
    reply = apiagent.openai_compatible_converse("hello", search=False)
    assert reply.text == "ok"
    assert reply.usage_complete is False


@pytest.mark.parametrize("body", [[], "unexpected", None])
def test_compatible_agent_refuses_non_object_response_bodies(monkeypatch, body):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    monkeypatch.setattr(
        "app.providers._http.post_json_or_why",
        lambda *args, **kwargs: (body, ""),
    )
    reply = apiagent.openai_compatible_converse("hello", search=False)
    assert reply.error == "OpenAI-compatible endpoint returned an invalid response"
    assert "fixture-secret" not in reply.error


def test_compatible_agent_rejects_negative_usage_counts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr("app.keys.search_providers", lambda: [])
    monkeypatch.setattr(
        "app.providers._http.post_json_or_why",
        lambda *args, **kwargs: ({
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": -1, "completion_tokens": 2},
        }, ""),
    )
    reply = apiagent.openai_compatible_converse("hello", search=False)
    assert reply.text == "ok"
    assert reply.tokens_in is None
    assert reply.tokens_out == 2
    assert reply.usage_complete is False


def test_compatible_agent_caps_unknown_tool_calls_too(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr("app.keys.search_providers", lambda: ["exa"])
    monkeypatch.setattr("app.providers._searcher", lambda *args: (lambda *a: [], "exa"))
    monkeypatch.setattr("app.providers.fetch.reader", lambda: lambda url: "")
    calls = [{"id": str(index), "function": {
        "name": "unrecognized", "arguments": "{}",
    }} for index in range(9)]
    monkeypatch.setattr(
        "app.providers._http.post_json_or_why",
        lambda *args, **kwargs: ({
            "choices": [{"message": {"content": None, "tool_calls": calls}}],
        }, ""),
    )
    reply = apiagent.openai_compatible_converse("hello")
    assert reply.error == "OpenAI-compatible endpoint exceeded the search call limit"
    assert reply.tool_calls == 0


def test_compatible_agent_researcher_keeps_usage_incomplete(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    researcher = apiagent.ApiAgentResearcher(
        apiagent.OPENAI_COMPATIBLE,
        model="custom-model",
        home=tmp_path,
        converse=lambda *args, **kwargs: mistral.Reply(
            text="ok", tokens_in=3, usage_complete=False),
    )
    assert researcher.ask("hello", allow_tools=False) == "ok"
    assert researcher.usage_complete is False


def test_compatible_api_agent_is_a_selectable_preferences_row(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "available", lambda: [])
    monkeypatch.setattr(harness, "found_but_unusable", lambda: [])
    monkeypatch.setattr(apiagent, "available", lambda path=None: [apiagent.OPENAI_COMPATIBLE])
    monkeypatch.setattr(apiagent, "models_for", lambda *args: [])
    monkeypatch.setattr("app.prefs.local_agent_rows", lambda conn: ([], [], []))
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        choices = prefs.choices(conn)
    finally:
        conn.close()
    row = next(one for one in choices["harnesses"] if one["id"] == "openai-api")
    assert row["model_freeform"] is True
    assert row["llm_selectable"] is True
