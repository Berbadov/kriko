import asyncio
import json

import httpx
import pytest

from app.searchbench.accuracy import consensus, grade_result, primary_citations
from app.searchbench.agent import research
from app.searchbench.config import MODELS
from app.searchbench.federated import FederatedRetrieval
from app.searchbench.mega import run_profile
from app.searchbench.mega_report import summarize, paired
from app.searchbench.metrics import ledger
from app.searchbench.transport import Wire


def fixture_case():
    return {"id": "test", "question": "Identify the model and scope.", "category": "category", "complexity": "easy", "deadline_s": 2,
            "criteria": [{"id": "identity", "critical": True, "fact": "Exact model"}, {"id": "scope", "fact": "Exact scope"}],
            "primary_domains": ["manufacturer.test"], "primary_min": 1}


def fixture_judgement():
    return {"criteria": [{"id": "identity", "credit": 1}, {"id": "scope", "credit": 1}],
            "claims": [{"text": "Correct fact", "correct": True, "support": "supported", "source_ids": ["S1"]}],
            "scope_violations": [], "summary": "Supported"}


def test_accuracy_requires_critical_facts_grounding_and_an_actual_primary_citation():
    case = fixture_case()
    row = {"status": "ok", "answer": "Correct fact [S1]", "sources": [{"id": "S1", "url": "https://manufacturer.test/spec"}]}
    assert grade_result(fixture_judgement(), case, row)["accepted"]
    row["sources"][0]["url"] = "https://manufacturer.test.reviews.example/spec"
    assert not grade_result(fixture_judgement(), case, row)["accepted"]
    row["sources"][0]["url"] = "https://manufacturer.test/spec"
    judgement = fixture_judgement()
    judgement["criteria"][0]["credit"] = .5
    assert not grade_result(judgement, case, row)["accepted"]
    judgement = fixture_judgement()
    judgement["claims"][0]["support"] = "insufficient"
    assert not grade_result(judgement, case, row)["accepted"]


def test_correct_clarification_does_not_need_an_invented_citation():
    case = fixture_case()
    case["primary_min"] = 0
    judgement = fixture_judgement()
    judgement["claims"] = []
    row = {"status": "ok", "answer": "What exact model and year is this?", "sources": []}
    assert grade_result(judgement, case, row)["accepted"]


def test_judge_cannot_omit_criteria_or_invent_supporting_source_ids():
    row = {"status": "ok", "answer": "Fact [S1]", "sources": [{"id": "S1", "url": "https://manufacturer.test"}]}
    judgement = fixture_judgement()
    judgement["criteria"] = judgement["criteria"][:1]
    with pytest.raises(ValueError):
        grade_result(judgement, fixture_case(), row)
    judgement = fixture_judgement()
    judgement["claims"][0]["source_ids"] = ["S999"]
    with pytest.raises(ValueError):
        grade_result(judgement, fixture_case(), row)


def test_primary_sources_exclude_publisher_hosted_forums_and_duplicate_translations():
    sources = [{"id": "S1", "url": "https://manufacturer.test/community/post"},
               {"id": "S2", "url": "https://manufacturer.test/en-us/manual?guid=abc&lang=en"},
               {"id": "S3", "url": "https://manufacturer.test/de-de/manual?guid=abc&lang=de"},
               {"id": "S4", "url": "https://manufacturer.test/en-us/spec?guid=def"}]
    assert primary_citations("Facts [S1] [S2] [S3] [S4]", sources, ["manufacturer.test"]) == ["S2", "S4"]


def test_disagreement_and_unscored_answers_do_not_become_consensus_passes():
    yes = {"status": "scored", "accepted": True, "fact_recall": 1}
    no = {"status": "scored", "accepted": False, "fact_recall": .5}
    assert consensus([yes, no])["accepted"] is False
    assert consensus([yes, no])["judge_agreement"] is False
    assert consensus([yes, {"status": "judge_error"}])["accepted"] is None


def test_a_judges_supported_label_without_citations_is_downgraded_not_trusted():
    judgement = fixture_judgement()
    judgement["claims"][0]["source_ids"] = []
    row = {"status": "ok", "answer": "A claim [S1]", "sources": [{"id": "S1", "url": "https://manufacturer.test/spec"}]}
    result = grade_result(judgement, fixture_case(), row)
    assert not result["accepted"] and result["citation_support_rate"] == 0
    assert result["normalizations"]


def sse(delta, finish="stop"):
    return httpx.Response(200, text="data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}],
                                                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}}) + "\n\ndata: [DONE]\n\n")


def test_missing_identity_can_end_with_a_clarification_without_wasteful_search(monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    def respond(request):
        assert request.url.path.endswith("chat/completions")
        return sse({"tool_calls": [{"index": 0, "id": "c", "function": {"name": "clarify", "arguments": '{"question":"What exact model/year?"}'}}]}, "tool_calls")
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            row = await research(Wire(client), MODELS["mercury-3"], "deepseek-content", fixture_case(), strategy="parallel")
            assert row["status"] == "ok" and row["answer_type"] == "clarification"
            assert row["search_requests"] == 0 and row["tool_calls"] == 1
    asyncio.run(exercise())


def test_federation_counts_all_providers_and_keeps_global_ids(monkeypatch):
    for key in ("DEEPSEEK_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(key, "fake")
    def respond(request):
        if "deepseek" in request.url.host:
            return httpx.Response(200, json={"results": [{"url": "https://same.test/page#one", "content": "Page text"}]})
        return httpx.Response(200, json={"results": [{"url": "https://same.test/page#two", "content": "Snippet"},
                                                    {"url": "https://" + request.url.host + "/source", "content": "Other"}], "usage": {"credits": 1}})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            wire = Wire(client)
            retrieval = FederatedRetrieval(wire)
            sources = await retrieval.search("query")
            assert len(sources) == 3 and len(wire.events) == 3
            assert len({s["id"] for s in sources}) == len(sources)
            assert set(s["url"] for s in sources) == set(retrieval.sources)
            assert len(retrieval.owners["https://same.test/page"]) == 3
    asyncio.run(exercise())


def test_verification_charges_both_models_and_distinguishes_draft_latency(monkeypatch):
    monkeypatch.setenv("MERCURY_API_KEY", "fake")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    def respond(request):
        if request.url.path.endswith("chat/completions"):
            payload = json.loads(request.content)
            return sse({"content": ("Revised" if payload["model"] == "mercury-3" else "Draft") + " answer [S1]."})
        return httpx.Response(200, json={"results": [{"url": "https://manufacturer.test/spec", "content": "Evidence"}]})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            row = await run_profile(Wire(client), "m25-verify-m3", fixture_case(), 3, 2000)
            assert row["answer"] == "Revised answer [S1]." and row["draft_answer"] == "Draft answer [S1]."
            assert row["model_calls"] == 2 and row["search_requests"] == 1
            assert row["tokens"]["total"] == 240
            assert row["first_answer_text_s"] >= row["first_draft_text_s"]
    asyncio.run(exercise())


@pytest.mark.parametrize("rate,expected", [(None, None), (.008, .008)])
def test_tavily_dollars_require_an_explicit_comparison_rate(monkeypatch, rate, expected):
    monkeypatch.setenv("TAVILY_API_KEY", "fake")
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [], "usage": {"credits": 1}}))) as client:
            wire = Wire(client, tavily_credit_usd=rate)
            await wire.post("tavily", "https://api.tavily.com", "/search", "TAVILY_API_KEY", {"query": "q"})
            assert wire.events[0]["cost_usd"] == expected
    asyncio.run(exercise())


def test_quality_costs_include_rejected_attempts_and_censored_bills_cannot_dominate():
    def row(profile, case, seconds, accepted, *, complete=True):
        value = ledger({"events": [{"kind": "model", "cost_usd": .01, "usage": {"prompt_tokens": 100, "completion_tokens": 20}}]})
        value.update(profile=profile, case=case, repetition=0, status="ok" if accepted else "timeout", total_s=seconds,
                     accuracy={"complete": True, "accepted": accepted, "fact_recall": 1 if accepted else 0, "judge_agreement": True, "scope_violation": False})
        if not complete:
            value.update(cost_complete=False, cost_usd=None)
        return value
    rows = [row("m25-deepseek", "a", 1, True), row("m25-deepseek", "b", 20, False),
            row("candidate", "a", 4, True), row("candidate", "b", 4, True, complete=False)]
    summary = {s["profile"]: s for s in summarize(rows)}
    assert summary["m25-deepseek"]["known_cost_per_accepted"] == .02
    assert summary["m25-deepseek"]["mean_attempt_s"] == 10.5
    assert summary["m25-deepseek"]["pareto"]
    assert not summary["candidate"]["pareto"]
    comparison = paired(rows)[0]
    assert comparison["pairs"] == 2 and comparison["time_delta_s_mean"] == -6.5
    assert comparison["cost_delta_usd_n"] == 1
    rows[0]["accuracy"]["complete"] = False
    incomplete = next(s for s in summarize(rows) if s["profile"] == "m25-deepseek")
    assert incomplete["pass_rate"] is None and incomplete["pass_rate_upper"] == .5
