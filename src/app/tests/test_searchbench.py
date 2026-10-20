"""Exercise the experimental harness at the HTTP boundary, with no paid requests."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from app.searchbench.agent import research
from app.searchbench.config import MODELS, token_cost, load_keys
from app.searchbench.metrics import normalized_usage, ledger, cluster_interval, paired_comparisons
from app.searchbench.report import aggregate, write_report, write_csvs
from app.searchbench.retrieval import Retrieval
from app.searchbench.transport import Wire


def run(coroutine):
    return asyncio.run(coroutine)


def sse(*parts):
    return httpx.Response(200, text="\n\n".join("data: " + json.dumps(p) for p in parts) + "\n\ndata: [DONE]\n\n")


def call(name, args, index=0):
    return {"index": index, "id": f"call{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_stream_handles_nulls_split_tool_arguments_and_usage(monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    def respond(request):
        return sse({"choices": None},
                   {"choices": [{"delta": {"tool_calls": None, "content": None}}]},
                   {"choices": [{"delta": {"content": [{"type": "thinking", "thinking": [{"type": "text", "text": "private"}]}]}}]},
                   {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c", "function": {"name": "search", "arguments": '{"query":'}}]}}]},
                   {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"q"}'}}]}, "finish_reason": "tool_calls"}]},
                   {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            message, event = await Wire(client).chat(MODELS["mercury-3"], [], [])
            assert message["tool_calls"][0]["function"] == {"name": "search", "arguments": '{"query":"q"}'}
            assert message["content"] is None and "first_text_s" not in event
            assert event["cost_usd"] == pytest.approx(.000017)
    run(exercise())


def test_truncated_generation_keeps_usage_and_partial_answer(monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    async def exercise():
        response = sse({"choices": [{"delta": {"content": "partial"}, "finish_reason": "length"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response)) as client:
            wire = Wire(client)
            with pytest.raises(ValueError):
                await wire.chat(MODELS["mercury-3"], [], [])
            assert wire.events[0]["cost_usd"] > 0
            assert wire.events[0]["message"]["content"] == "partial"
    run(exercise())


@pytest.mark.parametrize("variant,path,field,value,key", [
    ("deepseek-content", "/v1/tools/search", "need_content", True, "DEEPSEEK_API_KEY"),
    ("deepseek-snippets", "/v1/tools/search", "need_content", False, "DEEPSEEK_API_KEY"),
    ("exa-lite", "/search", "type", "lite", "EXA_API_KEY"),
    ("exa-auto", "/search", "type", "auto", "EXA_API_KEY"),
    ("tavily-fast", "/search", "search_depth", "fast", "TAVILY_API_KEY"),
    ("tavily-ultra-fast", "/search", "search_depth", "ultra-fast", "TAVILY_API_KEY"),
])
def test_search_variants_and_duplicate_coalescing(monkeypatch, variant, path, field, value, key):
    monkeypatch.setenv(key, "fake")
    requests = []
    def respond(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert request.url.path == path and payload[field] == value
        assert "api_key" not in payload
        return httpx.Response(200, json={"results": [{"url": "https://example.com/page#one", "content": "Evidence"}]})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            retrieval = Retrieval(Wire(client), variant)
            a, b = await asyncio.gather(retrieval.search("q"), retrieval.search("q"))
            assert a == b and a[0]["id"] == "S1" and a[0]["url"] == "https://example.com/page"
            assert len(requests) == 1 and retrieval.cache_hits == 1
            with pytest.raises(ValueError):
                await retrieval.fetch("https://unseen.example/page")
    run(exercise())


@pytest.mark.parametrize("strategy,expected", [("parallel", 2), ("sequential", 1)])
def test_full_agent_fetches_pages_and_runs_independent_tools_together(monkeypatch, strategy, expected):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    monkeypatch.setenv("EXA_API_KEY", "fake")
    model_calls, active, peak = 0, 0, 0
    async def respond(request):
        nonlocal model_calls, active, peak
        payload = json.loads(request.content)
        if request.url.path.endswith("chat/completions"):
            model_calls += 1
            if model_calls == 1:
                delta = {"tool_calls": [call("search", {"query": "a"}), call("search", {"query": "b"}, 1)]}
            elif model_calls == 2:
                delta = {"tool_calls": [call("fetch", {"url": "https://example.com/a"}), call("fetch", {"url": "https://other.test/b"}, 1)]}
            else:
                delta = {"content": "The answer [S1] agrees with [S2]."}
            return sse({"choices": [{"delta": delta, "finish_reason": "tool_calls" if "tool_calls" in delta else "stop"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.005)
        active -= 1
        url = ("https://example.com/a" if payload.get("query") == "a" else "https://other.test/b") if request.url.path == "/search" else payload["ids"][0]
        return httpx.Response(200, json={"results": [{"url": url, "text": "Evidence from page"}], "costDollars": {"total": .001}})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            row = await research(Wire(client), MODELS["mercury-3"], "exa-lite", {"id": "test", "question": "q"}, strategy=strategy)
            assert row["status"] == "ok"
            assert row["quality"]["pages_read"] == 2 and not row["quality"]["unknown_citations"]
            assert row["tokens"]["total"] == 360
            assert row["cost_complete"] and row["search_requests"] == row["fetch_requests"] == 2
            assert row["first_answer_text_s"] >= row["first_result_s"]
    run(exercise())
    assert peak == expected


def test_deadline_cancels_inflight_request_and_records_failure(monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    cancelled = []
    async def respond(request):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            row = await research(Wire(client), MODELS["mercury-3"], "exa-lite", {"id": "t", "question": "q"}, timeout=.01)
            assert row["status"] == "timeout" and row["http_requests"] == 1
            assert row["tokens"]["total"] is None and not row["cost_complete"]
    run(exercise())
    assert cancelled


def test_blocked_page_is_a_tool_error_and_agent_can_read_an_alternate(monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    monkeypatch.setenv("EXA_API_KEY", "fake")
    turn = 0
    async def respond(request):
        nonlocal turn
        payload = json.loads(request.content)
        if request.url.path.endswith("chat/completions"):
            turn += 1
            if turn == 1:
                delta = {"tool_calls": [call("search", {"query": "q"})]}
            elif turn == 2:
                delta = {"tool_calls": [call("fetch", {"url": "https://blocked.test/"})]}
            elif turn == 3:
                assert '"status": 403' in payload["messages"][-1]["content"]
                delta = {"tool_calls": [call("fetch", {"url": "https://alternate.test/"})]}
            else:
                delta = {"content": "Supported answer [S2]."}
            return sse({"choices": [{"delta": delta, "finish_reason": "tool_calls" if "tool_calls" in delta else "stop"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        if request.url.path == "/search":
            return httpx.Response(200, json={"results": [{"url": "https://blocked.test/"}, {"url": "https://alternate.test/"}]})
        if "blocked" in payload["ids"][0]:
            return httpx.Response(403)
        return httpx.Response(200, json={"results": [{"url": "https://alternate.test/", "text": "Original page evidence"}]})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            row = await research(Wire(client), MODELS["mercury-3"], "exa-lite", {"id": "t", "question": "q"})
            assert row["status"] == "ok" and row["quality"]["pages_fetched"] == 1
            assert any(e.get("status") == 403 for e in row["events"])
    run(exercise())


def test_inline_page_content_can_be_used_without_paying_for_duplicate_fetch(monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    turn = 0
    def respond(request):
        nonlocal turn
        if request.url.path.endswith("chat/completions"):
            turn += 1
            delta = {"tool_calls": [call("search", {"query": "q"})]} if turn == 1 else {"content": "Supported [S1]."}
            return sse({"choices": [{"delta": delta, "finish_reason": "tool_calls" if turn == 1 else "stop"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        assert request.url.path == "/v1/tools/search"
        return httpx.Response(200, json={"results": [{"url": "https://example.test/", "content": "Original page content"}]})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            row = await research(Wire(client), MODELS["mercury-3"], "deepseek-content", {"id": "t", "question": "q"})
            assert row["status"] == "ok" and row["quality"]["pages_read"] == 1
            assert row["fetch_requests"] == row["quality"]["pages_fetched"] == 0
    run(exercise())


def test_eager_bootstrap_preserves_unicode_in_the_actual_model_prompt(monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    def respond(request):
        if request.url.path.endswith("chat/completions"):
            prompt = json.loads(request.content)["messages"][-1]["content"]
            assert "Türkçe kaynak — 资料" in prompt
            return sse({"choices": [{"delta": {"content": "Evidence [S1]."}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        return httpx.Response(200, json={"results": [{"url": "https://example.test/", "content": "Türkçe kaynak — 资料"}]})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            row = await research(Wire(client), MODELS["mercury-3"], "deepseek-content", {"id": "t", "question": "q"}, strategy="eager")
            assert row["status"] == "ok" and row["search_requests"] == 1
    run(exercise())


def test_token_subsets_are_not_double_counted_and_failed_calls_are_charged():
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40}, "completion_tokens_details": {"reasoning_tokens": 5}}
    assert normalized_usage(usage) == {"input": 100, "cached_input": 40, "output": 20, "reasoning": 5, "total": 120}
    assert token_cost(MODELS["mercury-3"], usage) == pytest.approx(.0000134)
    row = ledger({"events": [{"kind": "model", "usage": usage, "error": "Truncated", "cost_usd": .01},
                             {"kind": "model", "usage": {}, "cost_usd": None},
                             {"kind": "/v1/tools/search", "cost_usd": .00075}]})
    assert row["tokens"]["total"] is None and row["known_tokens"]["total"] == 120
    assert row["known_cost_usd"] == pytest.approx(.01075) and row["cost_usd"] is None
    assert token_cost(replace(MODELS["mercury-3"], input_usd=None), usage) is None
    assert token_cost(MODELS["mercury-3"], {"prompt_tokens": True, "completion_tokens": -1}) is None


def test_statistics_keep_failures_pair_tasks_and_decline_small_sample_p95(tmp_path):
    rows = []
    for case, seconds in (("a", 1), ("b", 5)):
        for candidate, delta in (("reference", 0), ("candidate", -0.5)):
            for repetition in range(2):
                rows.append(ledger({"case": case, "repetition": repetition, "candidate": candidate, "model": candidate,
                                    "strategy": "parallel", "search": "deepseek-content", "status": "ok", "total_s": seconds + delta,
                                    "events": [{"kind": "model", "usage": {"prompt_tokens": 10, "completion_tokens": 2}, "cost_usd": .01}]}))
    rows[0]["status"] = "timeout"
    comparisons = paired_comparisons(rows, ("reference", "deepseek-content", "parallel"))
    assert comparisons[0]["successful_pairs"] == 3 and comparisons[0]["unpaired_or_failed"] == 1
    assert comparisons[0]["latency_delta_ci95"] == [-.5, -.5]
    summary = aggregate(rows)
    assert summary[0]["failures"] == 1 and summary[0]["known_cost_usd"] == .04
    assert summary[0]["p95_s"] is None
    assert cluster_interval([{"case": "a", "value": 2}], "value") is None
    path = tmp_path / "report.md"
    document = {"created_at": "test", "runs": rows, "baseline": ["reference", "deepseek-content", "parallel"]}
    write_report(document, path)
    assert "Tokens and cost" in path.read_text(encoding="utf-8")
    write_csvs(document, path.with_suffix(""))
    import csv
    with (tmp_path / "report.trials.csv").open(encoding="utf-8", newline="") as file:
        trials = list(csv.DictReader(file))
    assert len(trials) == 8 and trials[0]["status"] == "timeout" and trials[0]["tokens_total"] == "12"
    with (tmp_path / "report.requests.csv").open(encoding="utf-8", newline="") as file:
        requests = list(csv.DictReader(file))
    assert len(requests) == 8 and requests[0]["tokens_total"] == "12"


def test_dotenv_cannot_override_environment_or_load_arbitrary_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "existing")
    monkeypatch.delenv("SEARCHBENCH_UNRELATED", raising=False)
    path = tmp_path / "keys.env"
    path.write_text('MERCURY_API_KEY=replacement\nSEARCHBENCH_UNRELATED=bad\n', encoding="utf-8")
    load_keys(path)
    import os
    assert os.environ["MERCURY_API_KEY"] == "existing"
    assert "SEARCHBENCH_UNRELATED" not in os.environ
