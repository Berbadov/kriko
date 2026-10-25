"""The fixed Mercury 3 + DeepSeek stack, exercised without network access."""

import json
import threading
import time

import pytest

from app import keys, modelcatalogue
from app.providers import agentplan, apiagent, kriko_agent, mistral
from app.providers.kriko_agent_cache import RetrievalCache


@pytest.fixture(autouse=True)
def use_test_retrieval_cache(tmp_path, monkeypatch):
    path = tmp_path / "cache" / "kriko-agent.sqlite3"
    monkeypatch.setattr(
        kriko_agent, "RetrievalCache",
        lambda supplied=None: RetrievalCache(supplied or path),
    )


def _tool_call(index, name, arguments, call_id=None):
    return {
        "index": index,
        "id": call_id or f"call-{index}",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _emit_tool_call(on_event, name, arguments, *, index=0):
    on_event({"choices": [{
        "delta": {"tool_calls": [_tool_call(index, name, arguments)]},
        "finish_reason": "tool_calls",
    }]})
    on_event({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20}})


def _emit_text(on_event, text):
    on_event({"choices": [{
        "delta": {"content": text}, "finish_reason": "stop",
    }]})
    on_event({"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 30}})


def test_search_and_fetch_pacing_stays_below_five_qps_per_lane(monkeypatch):
    now = [0.0]
    sleeps = []
    old_next_at = dict(kriko_agent._next_at)

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(kriko_agent.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(kriko_agent.time, "sleep", sleep)
    with kriko_agent._pace_lock:
        kriko_agent._next_at.clear()
    try:
        kriko_agent._pace("search")
        kriko_agent._pace("search")
        assert sleeps == [kriko_agent.MIN_RETRIEVAL_INTERVAL_SECONDS]

        # The provider limits these lanes independently.
        kriko_agent._pace("fetch")
        assert len(sleeps) == 1
        kriko_agent._pace("fetch")
        assert sleeps == [kriko_agent.MIN_RETRIEVAL_INTERVAL_SECONDS] * 2
    finally:
        with kriko_agent._pace_lock:
            kriko_agent._next_at.clear()
            kriko_agent._next_at.update(old_next_at)


def test_search_then_fetch_returns_grounding_text_and_token_metrics(monkeypatch):
    text = "The 2025 Widget uses a removable 1 TB SSD."
    calls = []
    model_turn = 0

    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")

    def stream(url, payload, headers, timeout, on_event, *, cancel_event=None):
        nonlocal model_turn
        if url.endswith("/chat/completions"):
            assert headers["authorization"] == "Bearer fixture-mercury"
            assert payload["model"] == "mercury-3"
            assert payload["reasoning_effort"] == "low"
            assert payload["max_tokens"] == kriko_agent.DEFAULT_MAX_TOKENS
            assert 0.5 <= payload["temperature"] <= 1.0
            model_turn += 1
            if model_turn == 1:
                _emit_tool_call(on_event, "search", {"query": "2025 Widget SSD"})
            elif model_turn == 2:
                assert payload["tool_choice"] == "required"
                assert [tool["function"]["name"] for tool in payload["tools"]] == ["fetch"]
                _emit_tool_call(on_event, "fetch", {"url": "https://maker.example/spec"})
            else:
                assert "The 2025 Widget uses a removable 1 TB SSD." in payload["messages"][-1]["content"]
                _emit_text(on_event, "{\"findings\": []}")
            return 3, ""
        return 0, "unexpected endpoint"

    def post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        assert headers["authorization"] == "Bearer fixture-deepseek"
        if url.endswith("/tools/search"):
            assert payload["need_content"] is True
            return {"results": [{
                "url": "https://maker.example/spec#details",
                "title": "Widget specification",
                "content": "",
                "summary": "Manufacturer product specification.",
                "snippet": "Widget product details.",
            }]}, ""
        assert url.endswith("/tools/fetch")
        assert payload["url"] == "https://maker.example/spec"
        return {"title": "Widget specification", "content": text}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", post)
    reply = kriko_agent.converse("Research the exact Widget model")

    assert reply.error == ""
    assert reply.text == "{\"findings\": []}"
    assert reply.queries == ["2025 Widget SSD"]
    assert reply.retrieval_requests == 2
    assert reply.billed_tool_calls == 2
    assert reply.tool_calls == 2
    assert reply.tokens_in == 320
    assert reply.tokens_out == 70
    assert reply.usage_complete
    assert reply.sources["https://maker.example/spec"]["text"] == text
    assert len(calls) == 2
    assert model_turn == 3


def test_title_only_results_and_empty_fetch_cannot_ground_a_recommendation(monkeypatch):
    turns = 0
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")

    def stream(_url, payload, _headers, _timeout, on_event, *, cancel_event=None):
        nonlocal turns
        turns += 1
        if turns == 1:
            _emit_tool_call(on_event, "search", {"query": "Widget official specifications"})
        elif turns == 2:
            assert payload["tool_choice"] == "required"
            assert [tool["function"]["name"] for tool in payload["tools"]] == ["fetch"]
            _emit_tool_call(on_event, "fetch", {"url": "https://maker.example/widget"})
        else:
            _emit_text(on_event, "Buy the Widget; it has the best reliability.")
        return 1, ""

    def post(url, _payload, _headers, _timeout):
        if url.endswith("/tools/search"):
            return {"results": [{
                "url": "https://maker.example/widget", "title": "Widget",
                "snippet": "Official product page", "summary": "Specifications",
                "content": "",
            }]}, ""
        return {"url": "https://maker.example/widget", "title": "Widget", "content": ""}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", post)
    reply = kriko_agent.converse("Recommend the exact Widget")

    assert turns == 3
    assert reply.text == ""
    assert "Evidence gap" in reply.error
    assert reply.sources["https://maker.example/widget"]["text"] == ""


def test_successful_search_is_cached_between_conversations(monkeypatch, tmp_path):
    query = "2025 Widget SSD"
    text = "The 2025 Widget uses a removable 1 TB SSD."
    search_calls = []
    turns = 0
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")

    def stream(url, payload, headers, timeout, on_event, *, cancel_event=None):
        nonlocal turns
        turns += 1
        if turns in (1, 3):
            _emit_tool_call(on_event, "search", {"query": query, "count": 5})
        else:
            tool_text = " ".join(
                str(message.get("content") or "")
                for message in payload["messages"] if message.get("role") == "tool"
            )
            assert text in tool_text
            _emit_text(on_event, "{\"findings\": []}")
        return 1, ""

    def post(url, payload, headers, timeout):
        search_calls.append(payload)
        return {"results": [{
            "url": "https://maker.example/spec", "title": "Specifications",
            "content": text, "summary": "Maker specification", "snippet": text,
        }]}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", post)
    cache_path = tmp_path / "persistent.sqlite3"
    first = kriko_agent.converse("Research the Widget", cache_path=str(cache_path))
    second = kriko_agent.converse("Research the Widget", cache_path=str(cache_path))

    assert len(search_calls) == 1
    assert search_calls[0]["count"] == 4  # default thoroughness caps 5 at 4
    assert first.retrieval_requests == first.billed_tool_calls == 1
    assert second.retrieval_requests == second.billed_tool_calls == 0
    assert second.cache_hits == 1
    assert second.sources["https://maker.example/spec"]["text"] == text


def test_fetched_page_is_cached_and_remains_grounding_evidence(monkeypatch, tmp_path):
    url = "https://maker.example/spec"
    text = "The 2025 Widget uses a removable 1 TB SSD."
    search_calls = []
    fetch_calls = []
    turns = 0
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")

    def stream(_url, payload, _headers, _timeout, on_event, *, cancel_event=None):
        nonlocal turns
        turns += 1
        turn = (turns - 1) % 3
        if turn == 0:
            _emit_tool_call(on_event, "search", {"query": "Widget specs"})
        elif turn == 1:
            _emit_tool_call(on_event, "fetch", {"url": url})
        else:
            tool_text = " ".join(
                str(message.get("content") or "")
                for message in payload["messages"] if message.get("role") == "tool"
            )
            assert text in tool_text
            _emit_text(on_event, "{\"findings\": []}")
        return 1, ""

    def post(endpoint, payload, _headers, _timeout):
        if endpoint.endswith("/tools/search"):
            search_calls.append(payload)
            return {"results": [{
                "url": url, "title": "Specifications", "content": "",
                "summary": "Maker specification", "snippet": "Open the spec",
            }]}, ""
        fetch_calls.append(payload)
        return {"url": url, "title": "Specifications", "content": text}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", post)
    cache_path = tmp_path / "persistent.sqlite3"
    first = kriko_agent.converse("Research the Widget", cache_path=str(cache_path))
    second = kriko_agent.converse("Research the Widget", cache_path=str(cache_path))

    assert len(search_calls) == len(fetch_calls) == 1
    assert first.billed_tool_calls == 2
    assert second.billed_tool_calls == 0
    assert second.cache_hits == 2
    assert second.sources[url]["text"] == text


def test_duplicate_searches_share_one_request_and_empty_search_is_not_billed(monkeypatch):
    attempts = []
    turns = 0
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: "fixture")

    def stream(url, payload, headers, timeout, on_event, *, cancel_event=None):
        nonlocal turns
        turns += 1
        if turns == 1:
            on_event({"choices": [{
                "delta": {"tool_calls": [
                    _tool_call(0, "search", {"query": "same query"}),
                    _tool_call(1, "search", {"query": "same query"}),
                ]},
                "finish_reason": "tool_calls",
            }]})
            on_event({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 10}})
        else:
            _emit_text(on_event, "No primary results were returned.")
        return 1, ""

    def post(url, payload, headers, timeout):
        attempts.append(payload)
        return {"results": []}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", post)
    reply = kriko_agent.converse("Search once")

    assert reply.queries == ["same query"]
    assert reply.retrieval_requests == 1
    assert reply.billed_tool_calls == 0
    assert reply.tool_calls == 0
    assert len(attempts) == 1


def test_a_retrieval_that_never_answers_ends_the_turn_at_the_deadline(monkeypatch):
    """A search that hangs must cost the reader a reason, not the whole turn."""
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    searches: list[float] = []
    released = threading.Event()

    def stream(url, payload, headers, timeout, on_event, *, cancel_event=None):
        _emit_tool_call(on_event, "search", {"query": "widget gearbox failure", "count": 3})
        return 1, ""

    def post(url, payload, headers, timeout):
        searches.append(timeout)
        # Longer than the turn's own deadline, as a socket that dribbles is.
        released.wait(10.0)
        return {"results": []}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", post)
    steps: list[str] = []
    started = time.monotonic()
    try:
        reply = kriko_agent.converse("Research the Widget gearbox", timeout=0.5,
                                     on_step=steps.append)
    finally:
        released.set()
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"the turn waited on a retrieval for {elapsed:.1f}s"
    assert any("searching: widget gearbox failure" in line for line in steps), steps
    assert any("stopped" in line or "failed" in line for line in steps), steps
    assert reply.error, "the turn ends with a reason rather than hanging"


def test_the_chosen_kind_is_on_the_run_line_and_an_unknown_one_is_not_guessed(monkeypatch):
    """The reader's "all must be observable": which kind, which words, what came back."""
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    steps: list[str] = []
    asked: list[str] = []

    def stream(url, payload, headers, timeout, on_event, *, cancel_event=None):
        asked.append(str(payload["messages"][-1].get("role")))
        if len(asked) == 1:
            _emit_tool_call(on_event, "search",
                            {"query": "widget pump seal failure", "count": 3,
                             "kind": "forums"})
        elif len(asked) == 2:
            # A kind the app does not know: dropped, not guessed at.
            _emit_tool_call(on_event, "search",
                            {"query": "widget pump recall notice", "count": 3,
                             "kind": "bulletin boards"})
        else:
            _emit_text(on_event, "{\"findings\": []}")
        return 1, ""

    def post(url, payload, headers, timeout):
        return {"results": [{
            "url": "https://forum.example/thread/1", "title": "Thread",
            "content": "Owners report the seal fails.", "summary": "", "snippet": "",
        }]}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", post)
    reply = kriko_agent.converse("Research the Widget", on_step=steps.append)

    assert reply.error == ""
    assert "searching kind forums: widget pump seal failure" in steps
    assert any(line.startswith("searched kind forums: widget pump seal failure -> ")
               and "forum.example" in line for line in steps), steps
    assert "searching: widget pump recall notice" in steps, (
        "an unknown kind is left off the line rather than invented")
    assert not any("bulletin boards" in line for line in steps)


def test_successful_call_accounting_does_not_bill_an_empty_search(tmp_path):
    researcher = apiagent.ApiAgentResearcher(
        apiagent.KRIKO_AGENT,
        model=kriko_agent.MODEL,
        home=tmp_path,
        converse=lambda *_args, **_kwargs: mistral.Reply(),
    )
    reply = mistral.Reply(
        queries=["empty result query"],
        tokens_in=1_000_000,
        tokens_out=0,
        billed_tool_calls=0,
        retrieval_requests=1,
    )
    researcher._account(reply)

    assert researcher.tool_calls == 0
    assert researcher.retrieval_requests == 1
    assert researcher.spent == pytest.approx(0.10)
    assert modelcatalogue.tool_price("mercury", "deepseek_search", tmp_path) == 0.00075


def test_agent_is_offered_only_when_both_stack_keys_exist(monkeypatch):
    rows = {provider.id: False for provider in keys.PROVIDERS}
    rows["mercury"] = True
    monkeypatch.setattr(keys, "status", lambda *args, **kwargs: [
        {"id": name, "present": present} for name, present in rows.items()
    ])
    def require(provider, **_kwargs):
        if rows.get(provider):
            return f"fixture-{provider}"
        raise RuntimeError("missing")

    monkeypatch.setattr(keys, "require", require)
    assert apiagent.KRIKO_AGENT not in apiagent.available()
    rows["deepseek"] = True
    assert apiagent.KRIKO_AGENT in apiagent.available()


def test_shared_or_trial_keys_make_kriko_agent_available(monkeypatch):
    monkeypatch.setattr(keys, "status", lambda *args, **kwargs: [
        {"id": provider.id, "present": False} for provider in keys.PROVIDERS
    ])
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"resolved-{provider}")
    assert apiagent.KRIKO_AGENT in apiagent.available()


def test_toolless_mercury_prose_is_not_accepted_as_a_researched_answer(monkeypatch):
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    steps: list[str] = []

    def stream(_url, _payload, _headers, _timeout, on_event, **_kwargs):
        _emit_text(on_event, "I will search the web and get back to you.")
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    reply = kriko_agent.converse("Research the Widget", timeout=10,
                                 on_step=steps.append)
    assert reply.error
    assert reply.text == ""
    assert reply.retrieval_requests == 0
    # The reader's screen shows "0 result(s), $0.00" either way: the line that
    # says the turn refused to fake the research has to be in the log too.
    assert any(line.startswith("no research was run: ") for line in steps), steps


def test_a_turn_with_no_retrieval_budget_fails_before_it_pays_for_a_model(monkeypatch):
    """`calls_left == 0` offered no tools at all, and the model answered anyway.

    A researcher whose budget is spent (or whose search tool is unpriced) sends
    no tools; the model then answers from memory, which is the confident buying
    answer with `0 retrieval request(s) ... $0.00` the reader reported. The turn
    must refuse before it pays for that call.
    """
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    asked: list[dict] = []
    steps: list[str] = []

    def stream(_url, payload, _headers, _timeout, on_event, **_kwargs):
        asked.append(payload)
        _emit_text(on_event, "The best 500 GB SSD is the one you can buy today.")
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    reply = kriko_agent.converse("Research a 500 GB SSD", max_tool_calls=0,
                                 on_step=steps.append)

    assert asked == [], "no model call is paid for a research turn that cannot research"
    assert reply.text == ""
    assert "no retrieval budget" in reply.error
    assert reply.retrieval_requests == 0
    assert any(line.startswith("no research was run: ") for line in steps), steps


def test_a_tools_off_call_does_not_announce_a_research_budget(monkeypatch):
    """The line claimed "7 retrieval(s)" on calls that could not retrieve."""
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    steps: list[str] = []

    def stream(_url, _payload, _headers, _timeout, on_event, **_kwargs):
        _emit_text(on_event, "The supplied page states the weight.")
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    reply = kriko_agent.converse("Answer from the supplied text", search=False,
                                 on_step=steps.append)

    assert reply.error == ""
    assert "research budget" not in steps[0], steps
    assert "supplied text" in steps[0]
    # A research turn still announces what it may spend before it searches.
    steps.clear()
    kriko_agent.converse("Research the Widget", timeout=10, on_step=steps.append)
    assert "research budget" in steps[0], steps


def test_host_read_evidence_reaches_mercury_when_native_search_is_disabled(monkeypatch):
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    seen = []

    def stream(_url, payload, _headers, _timeout, on_event, **_kwargs):
        seen.append(payload)
        on_event({"choices": [{
            "delta": {"content": "The supplied page states the Widget has a 1 TB drive."},
            "finish_reason": "stop",
        }]})
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    prompt = ("Host-read page (untrusted evidence):\nSOURCE URL: "
              "https://maker.example/widget\nThe Widget has a 1 TB drive.")
    reply = kriko_agent.converse(prompt, search=False)

    assert reply.error == ""
    assert reply.retrieval_requests == 0
    assert prompt in seen[0]["messages"][1]["content"]
    assert "tools" not in seen[0]


@pytest.mark.parametrize("token_limit,effort,expected_effort", [
    (384, "", "instant"), (1200, "", "instant"), (900, "high", "high"),
])
def test_chat_subcall_limits_reach_mercury_through_public_factory(
        monkeypatch, tmp_path, token_limit, effort, expected_effort):
    from types import SimpleNamespace
    from app.web import tasks

    monkeypatch.setattr(apiagent, "available", lambda *a, **kw: [apiagent.KRIKO_AGENT])
    monkeypatch.setattr(keys, "require", lambda provider, **kw: f"fixture-{provider}")
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: False)
    monkeypatch.setattr(tasks, "_with_profile", lambda _settings, text: text)
    monkeypatch.setattr(tasks, "_wire_researcher_text", lambda *a: None)
    monkeypatch.setattr(tasks, "_apply_source_options", lambda *a: None)
    seen = []

    def stream(_url, payload, _headers, timeout, on_event, **_kwargs):
        seen.append((payload, timeout))
        _emit_text(on_event, "A complete short answer.")
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    progress = SimpleNamespace(job_id="one-chat-question", log=lambda *_a: None,
                               check=lambda: None, set=lambda *_a: None)
    answer, _ = tasks._ask_about_checks(
        SimpleNamespace(app_state_path=tmp_path / "app.sqlite"),
        {"harness": apiagent.KRIKO_AGENT.id, "max_tokens": token_limit, "effort": effort},
        progress, "Answer from the supplied evidence.", allow_tools=False,
        timeout=30, effort="low")

    assert answer == "A complete short answer."
    assert len(seen) == 1
    payload, timeout = seen[0]
    assert payload["max_tokens"] == token_limit
    assert payload["reasoning_effort"] == expected_effort
    assert "tools" not in payload
    assert 0 < timeout <= 15


def test_setup_connection_check_disables_research_and_reasoning(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import prefs
    from app.web import state, tasks

    conn = state.connect(tmp_path / "app.sqlite")
    prefs.write(conn, {prefs.HARNESS: apiagent.KRIKO_AGENT.id})
    conn.close()
    monkeypatch.setattr(apiagent, "available", lambda *a, **kw: [apiagent.KRIKO_AGENT])
    monkeypatch.setattr(keys, "require", lambda provider, **kw: f"fixture-{provider}")
    monkeypatch.setattr(tasks, "_with_profile", lambda _settings, text: text)
    monkeypatch.setattr(tasks, "_wire_researcher_text", lambda *a: None)
    seen = []

    def stream(_url, payload, _headers, timeout, on_event, **_kwargs):
        seen.append(payload)
        assert "tools" not in payload
        assert payload["reasoning_effort"] == "instant"
        assert 128 <= payload["max_tokens"] <= 512
        assert timeout <= 15
        _emit_text(on_event, "Kriko connection verified.")
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    progress = SimpleNamespace(job_id="connection-check", log=lambda *_a: None,
                               check=lambda: None, set=lambda *_a: None)
    result = tasks.agent_check(SimpleNamespace(app_state_path=tmp_path / "app.sqlite"), {}, progress)
    assert result["answer"] == "Kriko connection verified."
    assert result["agent"]["id"] == apiagent.KRIKO_AGENT.id
    assert len(seen) == 1


@pytest.mark.parametrize("partial", ["An unfinished answer", "{\"decision\":"])
def test_token_limited_reply_is_rejected_instead_of_returned_as_success(monkeypatch, partial):
    monkeypatch.setattr(keys, "require", lambda provider, **kw: f"fixture-{provider}")

    def stream(_url, payload, _headers, _timeout, on_event, **_kwargs):
        assert payload["max_tokens"] == 64
        on_event({"choices": [{"delta": {"content": partial}, "finish_reason": "length"}]})
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    reply = kriko_agent.converse("A short answer", search=False, max_tokens=64)
    assert reply.text == ""
    assert "token limit" in reply.error


def test_a_cut_off_answer_is_kept_for_a_caller_that_can_repair_it(monkeypatch):
    """The Golf catalog that was paid for and thrown away at the response limit."""
    monkeypatch.setattr(keys, "require", lambda provider, **kw: f"fixture-{provider}")
    partial = '{"claims": [{"title": "one"}, {"title": "two"}, {"title": "thr'

    def stream(_url, _payload, _headers, _timeout, on_event, **_kwargs):
        on_event({"choices": [{"delta": {"content": partial}, "finish_reason": "length"}]})
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    reply = kriko_agent.converse("Author the catalog", search=False, keep_partial=True)
    assert reply.error == ""
    assert reply.text == partial
    assert reply.truncated is True
    # The caller's own repair closes it at the last whole entry.
    from app import packauthor
    payload, note = packauthor.read_payload(reply.text)
    assert [claim["title"] for claim in payload["claims"]] == ["one", "two"]
    assert "stopped mid-object" in note


def test_a_cut_off_tool_call_is_never_kept(monkeypatch):
    monkeypatch.setattr(keys, "require", lambda provider, **kw: f"fixture-{provider}")

    def stream(_url, _payload, _headers, _timeout, on_event, **_kwargs):
        on_event({"choices": [{"delta": {"tool_calls": [{
            "index": 0, "id": "call-0",
            "function": {"name": "search", "arguments": '{"query": "an unfin'}}]},
            "finish_reason": "length"}]})
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    reply = kriko_agent.converse("Research the Widget", keep_partial=True)
    assert reply.text == ""
    assert reply.truncated is False
    assert "token limit" in reply.error


def test_authoring_is_given_a_ceiling_for_a_whole_catalog_and_keeps_a_cut_off_reply():
    from types import SimpleNamespace

    from app.web import tasks

    api = SimpleNamespace(keep_partial=False, max_tokens=None)
    tasks._for_authoring(api)
    assert api.keep_partial is True
    assert api.max_tokens == kriko_agent.AUTHORING_MAX_TOKENS
    assert kriko_agent.AUTHORING_MAX_TOKENS > kriko_agent.DEFAULT_MAX_TOKENS
    assert kriko_agent.AUTHORING_MAX_TOKENS <= kriko_agent.MAX_OUTPUT_TOKENS

    # A ceiling the caller already chose stays theirs.
    chosen = SimpleNamespace(keep_partial=False, max_tokens=4096)
    tasks._for_authoring(chosen)
    assert chosen.max_tokens == 4096

    # A CLI or a local model has neither setting: nothing is added to it.
    cli = SimpleNamespace()
    tasks._for_authoring(cli)
    assert vars(cli) == {}


def test_kriko_agent_caps_a_parent_research_budget(monkeypatch):
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    timeouts = []
    steps = []

    def stream(_url, _payload, _headers, timeout, on_event, **_kwargs):
        timeouts.append(timeout)
        _emit_text(on_event, "The answer is grounded in the supplied research.")
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    kriko_agent.converse("Research the Widget", timeout=900, on_step=steps.append)
    assert timeouts and max(timeouts) <= kriko_agent.TIMEOUT_SECONDS
    assert f"{kriko_agent.MAX_TURN_SECONDS:.0f} s" in steps[0]
    assert "900 s" not in steps[0]


def test_saved_agent_controls_reach_the_mercury_adapter(monkeypatch, tmp_path):
    from app import prefs
    from app.web import state

    app_state_path = tmp_path / "app.sqlite"
    conn = state.connect(app_state_path)
    try:
        prefs.write(conn, {
            prefs.KRIKO_AGENT_THOROUGHNESS: "85",
            prefs.KRIKO_AGENT_VALIDATION_SENSITIVITY: "95",
        })
    finally:
        conn.close()

    called = {}
    monkeypatch.setattr(
        kriko_agent, "converse",
        lambda prompt, **kwargs: called.update(prompt=prompt, **kwargs),
    )
    researcher = apiagent.ApiAgentResearcher(
        apiagent.KRIKO_AGENT, app_state_path=app_state_path,
    )
    researcher._stream_converse(
        "brief", model=kriko_agent.MODEL, timeout=10, search=True,
        cancel_event=None, on_text=None,
    )

    assert called["thoroughness"] == 85
    assert called["validation_sensitivity"] == 95
    assert called["cache_path"] == str(
        tmp_path / "cache" / "kriko-agent.sqlite3"
    )


def test_fixed_agent_uses_mercury_3_and_lists_deepseek_search():
    researcher = apiagent.ApiAgentResearcher(
        apiagent.KRIKO_AGENT,
        converse=lambda *_args, **_kwargs: mistral.Reply(),
    )
    assert researcher.model == "mercury-3"
    assert researcher.search_provider == "DeepSeek Search"
    assert apiagent.models_for(apiagent.KRIKO_AGENT)[0] == "mercury-3"


def test_mercury_3_envelope_is_within_the_models_limits(monkeypatch):
    assert kriko_agent.MODEL == "mercury-3"
    # The provider's documented range, not a preference: 0.1 was a Mercury 2.5
    # value and Mercury 3 refuses it.
    assert 0.5 <= kriko_agent.TEMPERATURE <= 1.0
    assert kriko_agent.MAX_OUTPUT_TOKENS == 131_072

    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    too_many = kriko_agent.converse(
        "Research the Widget", search=False,
        max_tokens=kriko_agent.MAX_OUTPUT_TOKENS + 1,
    )
    assert "131072" in too_many.error


def test_picked_kriko_agent_uses_the_fixed_stack_through_the_harness(monkeypatch):
    monkeypatch.setattr(apiagent, "available",
                        lambda *args, **kwargs: [apiagent.KRIKO_AGENT])
    researcher = harness_researcher_for_test()
    assert isinstance(researcher, apiagent.ApiAgentResearcher)
    assert researcher.model == "mercury-3"
    assert researcher.search_provider == "DeepSeek Search"


@pytest.mark.parametrize("level,expected", [
    (0, (3, 2)), (50, (5, 4)), (100, (8, 5)),
])
def test_thoroughness_sets_search_and_result_limits(level, expected):
    assert kriko_agent.thoroughness_limits(level) == expected


def test_persistent_cache_obeys_ttl_and_survives_a_new_adapter(tmp_path):
    path = tmp_path / "cache.sqlite3"
    one = RetrievalCache(path)
    one.put("search", "query|3", {"results": [{"url": "https://x.test"}]},
            ttl_seconds=20, now=100)

    assert RetrievalCache(path).get("search", "query|3", now=119) == {
        "results": [{"url": "https://x.test"}],
    }
    assert RetrievalCache(path).get("search", "query|3", now=120) is None


def test_tool_context_is_bounded_and_keeps_source_urls():
    call_id = "c1"
    url = "https://maker.example/spec"
    result = {"results": [{
        "url": url, "title": "Widget specs", "snippet": "Details",
        "summary": "The maker page", "page_text": "evidence " * 2000,
    }]}
    budget = 700
    content = kriko_agent._fit_tool_message(result, call_id, budget)
    message = {"role": "tool", "tool_call_id": call_id, "content": content}

    assert content
    assert kriko_agent._message_size(message) <= budget
    packed = json.loads(content)
    assert packed["results"][0]["url"] == url
    assert packed["results"][0]["page_text"]
    assert len(packed["results"][0]["page_text"]) < len(result["results"][0]["page_text"])


def test_tool_view_clips_page_text_without_mutating_the_grounding_copy():
    long_text = "evidence " * 900
    payload = {"results": [{"url": "https://maker.example/spec", "page_text": long_text}]}
    view = kriko_agent._tool_view(payload)

    assert len(view["results"][0]["page_text"]) == kriko_agent.MAX_TOOL_TEXT_CHARS
    assert payload["results"][0]["page_text"] == long_text
    assert kriko_agent.MAX_SOURCE_CHARS > kriko_agent.MAX_TOOL_TEXT_CHARS


def test_catalogue_prices_mercury_3_at_its_published_rates():
    row = modelcatalogue.load()["mercury-3"]
    assert row["provider"] == "mercury"
    assert row["context"] == 1_000_000
    assert row["usd_in"] == pytest.approx(0.10)
    assert row["usd_out"] == pytest.approx(0.35)


def test_validation_sensitivity_requires_longer_and_then_exact_quotes():
    source = "The 2025 Widget uses a removable 1 TB SSD."
    retyped = "the 2025 widget uses a removable 1 tb ssd."
    assert kriko_agent.validated_quote(source, "1 TB SSD", 0) == "1 TB SSD"
    assert kriko_agent.validated_quote(source, retyped, 50) == source
    assert kriko_agent.validated_quote(source, retyped, 100) == ""
    assert kriko_agent.validated_quote(source, source, 100) == source


def harness_researcher_for_test():
    from app.providers import harness_researcher

    return harness_researcher(
        preferred="kriko-agent",
        model="mistral-large-latest",
    )


# ── the plan, the identity flag, freshness and the record ────────────────────

def _scripted_stack(monkeypatch, turns, results_for):
    """Mercury says `turns[i]` on its i-th call; DeepSeek answers `results_for(query)`.

    Returns the list of payloads Mercury was sent, so a test can read exactly
    what the model was shown between rounds.
    """
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    sent: list[dict] = []

    def stream(url, payload, headers, timeout, on_event, *, cancel_event=None):
        sent.append(json.loads(json.dumps(payload)))
        turn = turns[min(len(sent), len(turns)) - 1]
        if turn[0] == "search":
            _emit_tool_call(on_event, "search", turn[1])
        else:
            _emit_text(on_event, turn[1])
        return 1, ""

    def post(url, payload, headers, timeout):
        return {"results": results_for(payload["query"])}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", post)
    return sent


def _row(url, title, content):
    return {"url": url, "title": title, "content": content, "summary": "", "snippet": ""}


def test_a_lookup_question_is_planned_with_a_smaller_budget(monkeypatch):
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    monkeypatch.setattr(kriko_agent, "post_sse_or_why",
                        lambda *a, **k: (0, "stop here"))

    def budget(question):
        steps: list[str] = []
        kriko_agent.converse("brief", question=question, thoroughness=100,
                             on_step=steps.append)
        return steps

    lookup = budget("What are the specs of the Widget X100?")
    assert "Kriko Agent: research budget 4 retrieval(s), 120 s" in lookup
    assert "plan: searching kinds: manufacturer" in lookup

    hunt = budget("Any known problems or recall notices for the Widget X100?")
    assert "Kriko Agent: research budget 8 retrieval(s), 120 s" in hunt
    assert "plan: searching kinds: forums, recalls" in hunt

    # No question handed in: the turn runs on the dial alone, as it always did.
    steps: list[str] = []
    kriko_agent.converse("brief", thoroughness=100, on_step=steps.append)
    assert "Kriko Agent: research budget 8 retrieval(s), 120 s" in steps
    assert not any(line.startswith("plan:") for line in steps)


def test_pages_are_flagged_by_whether_they_carry_the_products_own_words(monkeypatch):
    sent = _scripted_stack(
        monkeypatch,
        [("search", {"query": "widget x100 problems", "kind": "forums"}),
         ("text", "{\"findings\": []}")],
        lambda _query: [
            _row("https://forum.example/a", "Widget X100 thread",
                 "Owners of the Widget X100 report the seal fails."),
            _row("https://forum.example/b", "Gadget Y200 thread",
                 "Owners of the Gadget Y200 report the hinge cracks."),
        ],
    )
    steps: list[str] = []
    reply = kriko_agent.converse(
        "brief", question="Any known problems with the Widget X100?", on_step=steps.append)

    assert reply.error == ""
    shown = json.loads(sent[1]["messages"][-1]["content"])["results"]
    assert [row["about_product"] for row in shown] == [True, False]
    assert "about_product" in sent[0]["messages"][0]["content"]
    assert reply.record["pages"] == 2
    assert reply.record["on_product"] == 1 and reply.record["off_product"] == 1
    assert reply.record["kinds"] == ["forums"] and reply.record["missing"] == []
    assert any(line.startswith("record: 1 search(es)") for line in steps), steps


def test_the_flag_is_computed_for_each_question_and_never_stored_in_the_cache(monkeypatch):
    rows = [
        _row("https://forum.example/a", "Widget X100 thread", "The Widget X100 seal fails."),
        _row("https://forum.example/b", "Gadget Y200 thread", "The Gadget Y200 hinge cracks."),
    ]
    script = [("search", {"query": "owner reports", "kind": "forums"}),
              ("text", "{\"findings\": []}")]

    def shown_flags(question):
        sent = _scripted_stack(monkeypatch, script, lambda _query: rows)
        reply = kriko_agent.converse("brief", question=question)
        assert reply.error == ""
        return [row["about_product"]
                for row in json.loads(sent[1]["messages"][-1]["content"])["results"]]

    assert shown_flags("Any known problems with the Widget X100?") == [True, False]
    # The second turn is answered from the cache, about the other product.
    assert shown_flags("Any known problems with the Gadget Y200?") == [False, True]


def test_the_coverage_note_rides_beside_the_evidence_until_the_kind_is_searched(monkeypatch):
    sent = _scripted_stack(
        monkeypatch,
        [("search", {"query": "widget x100 seal failure", "kind": "forums"}),
         ("search", {"query": "widget x100 recall notice", "kind": "recalls"}),
         ("text", "{\"findings\": []}")],
        lambda _query: [_row("https://example.org/page", "Widget X100",
                             "The Widget X100 seal and recall notice.")],
    )
    steps: list[str] = []
    reply = kriko_agent.converse(
        "brief", question="Any known problems or recall notices for the Widget X100?",
        on_step=steps.append)

    assert reply.error == ""
    after_forums = json.loads(sent[1]["messages"][-1]["content"])
    assert [row["kind"] for row in after_forums["coverage"]["still_asked"]] == ["recalls"]
    assert "coverage: not yet searched: recalls" in steps
    after_recalls = json.loads(sent[2]["messages"][-1]["content"])
    assert "coverage" not in after_recalls
    assert reply.record["kinds"] == ["forums", "recalls"]
    assert reply.record["missing"] == []


def test_a_kind_asked_for_and_never_searched_is_reported_as_missing(monkeypatch):
    _scripted_stack(
        monkeypatch,
        [("search", {"query": "widget x100 seal failure", "kind": "forums"}),
         ("text", "{\"findings\": []}")],
        lambda _query: [_row("https://forum.example/a", "Widget X100",
                             "The Widget X100 seal fails.")],
    )
    reply = kriko_agent.converse(
        "brief", question="Any known problems or recall notices for the Widget X100?")
    assert reply.record["kinds"] == ["forums"]
    assert reply.record["missing"] == ["recalls"]


def test_the_record_counts_an_unlabelled_search_by_the_kind_its_words_ask_for(monkeypatch):
    _scripted_stack(
        monkeypatch,
        [("search", {"query": "widget x100 owners forum"}),
         ("text", "{\"findings\": []}")],
        lambda _query: [_row("https://forum.example/a", "Widget X100",
                             "The Widget X100 seal fails.")],
    )
    steps: list[str] = []
    reply = kriko_agent.converse("brief", on_step=steps.append)
    assert reply.record["kinds"] == ["forums"]
    # No question, no plan, and so no plan line: the log keeps its old shape.
    assert not any(line.startswith(("plan:", "record:")) for line in steps)
    assert "on_product" not in reply.record


def test_search_freshness_follows_the_kind_of_source(monkeypatch):
    stored: list[tuple[str, int]] = []

    class Recorder:
        def get(self, *_args, **_kwargs):
            return None

        def put(self, lane, key, payload, *, ttl_seconds, now=None):
            stored.append((key, ttl_seconds))

    monkeypatch.setattr(kriko_agent, "RetrievalCache", lambda supplied=None: Recorder())
    for query, kind in (("widget x100 notice", "recalls"),
                        ("widget x100 manual", ""),
                        ("widget x100 anything", "")):
        _scripted_stack(
            monkeypatch,
            [("search", {"query": query, **({"kind": kind} if kind else {})}),
             ("text", "{\"findings\": []}")],
            lambda _query: [_row("https://example.org/p", "Widget", "The Widget X100.")],
        )
        assert kriko_agent.converse("brief").error == ""

    ttl = {key.split("|")[0]: seconds for key, seconds in stored}
    assert ttl["widget x100 notice"] == agentplan.FRESHNESS_SECONDS["recalls"]
    # Unlabelled: the kind its own words ask for ("manual" asks for the maker's).
    assert ttl["widget x100 manual"] == agentplan.FRESHNESS_SECONDS["manufacturer"]
    # Asks for no kind: the standing default.
    assert ttl["widget x100 anything"] == kriko_agent.SEARCH_TTL_SECONDS


def test_the_researcher_merges_each_calls_record_across_the_turn(tmp_path):
    researcher = apiagent.ApiAgentResearcher(
        apiagent.KRIKO_AGENT, model=kriko_agent.MODEL, home=tmp_path,
        converse=lambda *_args, **_kwargs: mistral.Reply(),
    )
    researcher._account(mistral.Reply(record=agentplan.build_record(
        searches=2, kinds=["forums"], missing=["recalls"], pages=3, unreadable=0,
        cached=0, retrieved=3)))
    researcher._account(mistral.Reply(record=agentplan.build_record(
        searches=1, kinds=["recalls"], missing=[], pages=1, unreadable=1,
        cached=1, retrieved=1)))
    # A reply from an adapter that keeps no record changes nothing.
    researcher._account(mistral.Reply())

    assert researcher.agent_record["searches"] == 3
    assert researcher.agent_record["pages"] == 4
    assert researcher.agent_record["kinds"] == ["forums", "recalls"]
    assert researcher.agent_record["missing"] == []
