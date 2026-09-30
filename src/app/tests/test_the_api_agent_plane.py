"""B153: agent operations over Mistral's API, grounded on what the search returned.

The reader's report was "Agent operations are slow and not working properly".
The CLIs failed for reasons on their side of a process boundary, so the same
brief now also runs as one HTTP request. These hold the four promises that
makes:

* it runs only when the reader picked it, never because a key was saved;
* a quote is kept only if it is in the search text for its own url, and the
  kept quote is the source's own characters;
* every per-token run has a ceiling, and a spent one refuses the next request;
* an unpriced call makes the total `None`, never a smaller number.

No request leaves the machine here: `converse` is a fixture.
"""

import json
import threading
from types import SimpleNamespace

import pytest

from app import prefs, quicklook
from app.providers import (
    agent_ready, apiagent, bills_per_token, harness, harness_researcher, mistral,
    resolve_agent,
)
from app.web import state, tasks
from kriko.extract.grounding import is_grounded, loose_span
from kriko.research import BudgetExceeded
from kriko.research.base import ResearchTask

PAGE = "https://forum.example.org/t/1"
SNIPPET = "https://www.example.com/review"
TEXT = "Owners report that the pump’s seal fails near 80,000 km  and leaks."


def _search_entry(query: str, rows: dict) -> dict:
    return {"type": "tool.execution", "name": "web_search",
            "arguments": json.dumps({"query": query}),
            "info": {"result": json.dumps(rows)}}


def _opened_entry(url: str, content: str) -> dict:
    inner = json.dumps({"url": url, "title": "Thread", "content": content})
    return {"type": "tool.execution", "name": "web_search",
            "arguments": json.dumps({"query": url}),
            "info": {"result": [{"type": "text", "text": inner}]}}


def _body(text: str, *, calls: int = 2, usage: bool = True) -> dict:
    body = {"outputs": [
        _search_entry("pump seal failure", {"0": {
            "url": SNIPPET, "title": "<b>Review</b>",
            "description": "A &amp; B tested.", "snippets": ["The belt is noisy."]}}),
        _opened_entry(PAGE, TEXT),
        {"type": "message.output", "content": [{"type": "text", "text": text}]},
    ]}
    if usage:
        body["usage"] = {"prompt_tokens": 1000, "completion_tokens": 500,
                         "connector_tokens": 9000, "connectors": {"web_search": calls}}
    return body


# ── the provider's answer ───────────────────────────────────────────────────


def test_both_result_shapes_become_sources_with_their_text():
    reply = mistral.parse(_body("done"))
    assert reply.text == "done"
    assert reply.queries == ["pump seal failure", PAGE]
    assert reply.sources[SNIPPET]["title"] == "Review"
    assert "A & B tested." in reply.sources[SNIPPET]["text"]
    assert "The belt is noisy." in reply.sources[SNIPPET]["text"]
    assert reply.sources[PAGE]["text"] == TEXT


def test_the_search_text_the_model_read_is_billed_input():
    reply = mistral.parse(_body("done", calls=3))
    # `connector_tokens` is the search text put in front of the model: counting
    # only the prompt would report a 10k-token call as a 1k one.
    assert reply.tokens_in == 10000
    assert reply.tokens_out == 500
    assert reply.tool_calls == 3


def test_no_usage_block_is_cannot_count_never_zero():
    reply = mistral.parse(_body("done", usage=False))
    assert reply.tokens_in is None and reply.tokens_out is None


def test_a_refused_request_is_an_error_in_words(monkeypatch):
    sent = {}

    def post(url, payload, headers, timeout):
        sent.update(url=url, payload=payload)
        return None, "Mistral refused the key (401)"

    monkeypatch.setattr(mistral, "post_json_or_why", post)
    reply = mistral.converse("brief", api_key="fixture")
    assert reply.error == "Mistral refused the key (401)"
    assert sent["url"].endswith("/conversations")
    # Nothing is kept on Mistral's side, and a transcription task runs cold.
    assert sent["payload"]["store"] is False
    assert sent["payload"]["tools"] == [{"type": "web_search"}]
    assert sent["payload"]["completion_args"]["temperature"] == 0.0


def test_an_answer_with_no_text_is_an_error(monkeypatch):
    monkeypatch.setattr(mistral, "post_json_or_why",
                        lambda *a, **k: ({"outputs": []}, ""))
    assert mistral.converse("brief", api_key="fixture").error == "Mistral answered with no text"


# ── grounding ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("quote", [
    "the pump's seal fails near 80,000 km and leaks",   # straight apostrophe
    "THE PUMP’S SEAL FAILS",                              # case
    "fails near 80,000 km\nand leaks",                    # whitespace
])
def test_a_retyped_quote_is_found_and_returned_as_the_source_wrote_it(quote):
    span = loose_span(TEXT, quote)
    assert span
    # The point of returning the span: ingestion's check is exact.
    assert is_grounded(TEXT, span)


@pytest.mark.parametrize("quote", ["the pump never fails", "", "   "])
def test_a_quote_that_is_not_there_is_not_found(quote):
    assert loose_span(TEXT, quote) == ""


# ── the researcher ──────────────────────────────────────────────────────────


class _Converse:
    """`mistral.converse`, answering from a list and recording each prompt."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt, *, model, timeout):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _researcher(converse, *, model="", tmp_path=None):
    return apiagent.ApiAgentResearcher(apiagent.MISTRAL, model=model,
                                       converse=converse, home=tmp_path)


def _findings(*items) -> str:
    return "```json\n" + json.dumps({"queries": ["q"], "findings": list(items)}) + "\n```"


def _finding(url, quote, title="Seal failure"):
    return {"title": title, "domain": "cooling", "severity": "high",
            "quote": quote, "source_url": url, "body": "It leaks."}


def test_only_quotes_in_their_own_urls_search_text_are_kept(tmp_path):
    converse = _Converse(mistral.parse(_body(_findings(
        _finding(PAGE, "the pump's seal fails near 80,000 km"),
        _finding(PAGE, "the pump explodes at idle", title="Invented"),
        # True of the page, but claimed for a url that did not say it.
        _finding(SNIPPET, "the pump's seal fails", title="Wrong url"),
        _finding("https://never.searched.example/x", "anything", title="Unsearched"),
    ))))
    researcher = _researcher(converse, tmp_path=tmp_path)
    documents = researcher.gather(ResearchTask(
        subject_id="s", subject_label="Pump", subject_kind="part", pack_id="p",
        queries=("q",), max_documents=4))

    assert researcher.dropped == 3
    assert "3 finding(s) dropped" in researcher.note
    [document] = documents
    assert document.url == PAGE
    # The document is what the search returned, never the agent's paste.
    assert document.text == TEXT
    [kept] = researcher._by_url[PAGE]
    assert kept.quote == "the pump’s seal fails near 80,000 km"
    assert is_grounded(document.text, kept.quote)
    # The provider's queries, not the ones the model says it ran.
    assert researcher.queries_run == ["pump seal failure", PAGE]


def test_the_prompt_names_the_tool_and_a_ceiling_in_searches(tmp_path):
    converse = _Converse(mistral.parse(_body("ok")))
    researcher = _researcher(converse, tmp_path=tmp_path)
    researcher.budget_usd = 0.20
    assert researcher.ask("# Quick look") == "ok"
    [prompt] = converse.prompts
    assert prompt.startswith("# Quick look")
    assert "Your only tool is **web search**" in prompt
    # $0.20 at $0.03 a search: six, stated before any is spent.
    assert "At most **6 searches and page opens in total**" in prompt


def test_the_cost_is_tokens_plus_every_search(tmp_path):
    researcher = _researcher(_Converse(mistral.parse(_body("ok", calls=4))),
                             tmp_path=tmp_path)
    researcher.ask("brief")
    # 10k in and 500 out on mistral-small ($0.15 / $0.60 per million), plus
    # four searches at $0.03 each.
    expected = 10000 / 1e6 * 0.15 + 500 / 1e6 * 0.60 + 4 * 0.03
    assert researcher.spent == pytest.approx(expected)
    assert researcher.tokens_used == 10500
    assert researcher.model == "mistral-small-latest"
    assert researcher.cost_basis == "per_token"


def test_an_unpriced_model_is_cost_unknown_not_a_smaller_number(tmp_path):
    researcher = _researcher(_Converse(mistral.parse(_body("ok"))),
                             model="mistral-unlisted-9", tmp_path=tmp_path)
    researcher.ask("brief")
    assert researcher.spent is None


def test_a_spent_ceiling_refuses_the_next_request(tmp_path):
    converse = _Converse(mistral.parse(_body("ok", calls=10)))
    researcher = _researcher(converse, tmp_path=tmp_path)
    researcher.budget_usd = 0.10
    researcher.ask("first")
    with pytest.raises(BudgetExceeded):
        researcher.ask("second")
    assert len(converse.prompts) == 1


def test_an_error_reply_fails_the_run_in_the_providers_words(tmp_path):
    researcher = _researcher(_Converse(mistral.Reply(error="Mistral is over quota (429)")),
                             tmp_path=tmp_path)
    with pytest.raises(RuntimeError, match="over quota"):
        researcher.ask("brief")


def test_cancel_is_heard_while_the_request_is_out(tmp_path):
    release = threading.Event()

    def converse(prompt, *, model, timeout):
        release.wait(10)
        return mistral.parse(_body("late"))

    class Stop(Exception):
        pass

    polls = []

    def check():
        polls.append(1)
        if len(polls) > 1:
            raise Stop

    researcher = _researcher(converse, tmp_path=tmp_path)
    researcher._cancel_tick = 0.01
    researcher.check_cancelled = check
    try:
        with pytest.raises(Stop):
            researcher.ask("brief")
    finally:
        release.set()


# ── who runs: only the reader's pick ────────────────────────────────────────


@pytest.fixture
def machine(monkeypatch):
    """A machine whose CLIs and keys the test decides."""
    here = SimpleNamespace(clis=[], keyed=[])
    monkeypatch.setattr(harness, "chosen", lambda preferred="": (
        next((one for one in here.clis if one.id == preferred), None) if preferred
        else (here.clis[0] if here.clis else None)))
    monkeypatch.setattr(harness, "available", lambda: list(here.clis))
    monkeypatch.setattr(apiagent, "available", lambda path=None: list(here.keyed))
    return here


def test_the_picked_api_agent_runs_and_bills_per_token(machine):
    machine.keyed = [apiagent.MISTRAL]
    machine.clis = [harness.KNOWN[0]]
    assert resolve_agent("mistral-api") == (apiagent.MISTRAL, "")
    assert bills_per_token(preferred="mistral-api")
    assert not bills_per_token(preferred=harness.KNOWN[0].id)


def test_a_saved_key_alone_never_runs_it(machine):
    machine.keyed = [apiagent.MISTRAL]
    assert resolve_agent("") == (None, "")
    assert not agent_ready(preferred="")
    with pytest.raises(harness.NoHarness, match="runs only when picked"):
        harness_researcher(preferred="")


def test_a_pick_with_no_key_falls_back_to_a_cli_and_says_so(machine):
    machine.clis = [harness.KNOWN[0]]
    found, note = resolve_agent("mistral-api")
    assert found is harness.KNOWN[0]
    assert "Mistral API has no key here" in note
    machine.clis = []
    assert resolve_agent("mistral-api") == (None, "")
    assert not agent_ready(preferred="mistral-api")


def test_a_job_that_needs_markup_never_gets_the_api_agent(machine):
    machine.keyed = [apiagent.MISTRAL]
    machine.clis = [harness.KNOWN[0]]
    assert resolve_agent("mistral-api", api=False)[0] is harness.KNOWN[0]


def test_the_stored_pick_is_what_a_run_gets(machine, tmp_path):
    machine.keyed = [apiagent.MISTRAL]
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    try:
        prefs.write(conn, {prefs.HARNESS: "mistral-api"})
    finally:
        conn.close()
    assert agent_ready(path)
    assert tasks.default_backend(path) == "harness"
    researcher = harness_researcher(app_state_path=path)
    assert isinstance(researcher, apiagent.ApiAgentResearcher)


# ── ceilings ────────────────────────────────────────────────────────────────


def test_a_per_token_harness_run_gets_the_paid_planes_floor(machine):
    machine.keyed = [apiagent.MISTRAL]
    picked = {"backend": "harness", "harness": "mistral-api"}
    assert tasks._budget(picked) == tasks.DEFAULT_BUDGET_USD
    assert tasks._budget({**picked, "budget_usd": 0.05}) == 0.05
    machine.clis = [harness.KNOWN[0]]
    # A CLI is a subscription: no floor is invented for it.
    assert tasks._budget({"backend": "harness", "harness": harness.KNOWN[0].id}) == 0.0


def test_a_named_ceiling_reaches_only_a_metered_agent():
    metered = SimpleNamespace(cost_basis="per_token", budget_usd=0.0)
    flat = SimpleNamespace(cost_basis="subscription", budget_usd=0.0)
    for one in (metered, flat):
        tasks._cap_agent(one, {"budget_usd": 0.2})
    assert metered.budget_usd == 0.2
    assert flat.budget_usd == 0.0


# ── the quick look ──────────────────────────────────────────────────────────


def test_a_quick_look_quote_is_checked_against_its_urls_search_text():
    reply = "```json\n" + json.dumps({"risks": [
        {"title": "Seal", "url": PAGE, "quote": "the pump's seal fails"},
        {"title": "Invented", "url": PAGE, "quote": "it catches fire"},
        {"title": "Unsearched", "url": "https://other.example/x", "quote": "fails"},
    ]}) + "\n```"
    found = quicklook.parse(reply, {PAGE: TEXT})
    assert [one["title"] for one in found["risks"]] == ["Seal"]
    assert found["risks"][0]["sources"][0]["quote"] == "the pump’s seal fails"
    assert found["dropped"] == 2
    # A CLI keeps no sources, and then nothing is checked (the old behaviour).
    assert len(quicklook.parse(reply)["risks"]) == 3


# ── Settings and the extension ──────────────────────────────────────────────


def test_the_agents_row_lists_it_once_keyed_and_links_the_key_page_until(machine, tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        rows, missing = prefs.api_agent_rows(conn)
        assert rows == []
        assert missing[0]["id"] == "mistral-api"
        assert missing[0]["download_url"].startswith("https://console.mistral.ai/")
        machine.keyed = [apiagent.MISTRAL]
        rows, missing = prefs.api_agent_rows(conn)
        assert missing == []
        [row] = rows
        assert row["cost_basis"] == "per_token"
        assert "per token and per search" in row["needs_account"]
        assert row["llms"][0] == "mistral-small-latest"
    finally:
        conn.close()


def test_the_panel_names_the_bill_before_a_picked_api_agent_spends(machine, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import keys
    from app.web.app import create_app
    from app.web.deps import get_jobs
    from app.web.settings import Settings

    machine.keyed = [apiagent.MISTRAL]
    monkeypatch.setattr(keys, "ready", lambda *_, **__: False)
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        prefs.write(conn, {prefs.HARNESS: "mistral-api"})
    finally:
        conn.close()
    client = TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl")))
    submitted = []
    client.app.dependency_overrides[get_jobs] = lambda: SimpleNamespace(
        submit=lambda kind, params: submitted.append((kind, params)) or f"job-{kind}")
    try:
        plane = client.get("/api/extension/research-plane").json()
        assert plane["backend"] == "harness"
        assert plane["cost_basis"] == "per_token"
        assert plane["budget_usd"] == 0.20

        answer = client.post("/api/extension/research-plane", json={
            "q": "Unknown Widget", "allow_draft": True}).json()
        assert answer["cost_basis"] == "per_token"
        assert answer["harness"] == "mistral-api"
        assert answer["budget_usd"] == 0.70
        assert "Bills your Mistral API key" in answer["note"]
        budgets = {kind: params["budget_usd"] for kind, params in submitted}
        assert budgets == {"pack_author": apiagent.DEFAULT_BUDGET_USD, "quick_look": 0.20}
    finally:
        client.app.state.jobs.shutdown(wait=True)


# ── what the review found (B153) ────────────────────────────────────────────


def test_a_reply_with_no_usage_is_cost_unknown_not_free(tmp_path):
    researcher = _researcher(_Converse(mistral.parse(_body("ok", usage=False))),
                             tmp_path=tmp_path)
    researcher.ask("brief")
    assert researcher.spent is None
    assert researcher.tokens_used is None


def test_searches_the_reply_shows_are_billed_when_usage_omits_them(tmp_path):
    body = _body("ok")
    del body["usage"]["connectors"]
    researcher = _researcher(_Converse(mistral.parse(body)), tmp_path=tmp_path)
    researcher.ask("brief")
    # Two searches in the outputs: an absent count is not zero searches.
    expected = 10000 / 1e6 * 0.15 + 500 / 1e6 * 0.60 + 2 * 0.03
    assert researcher.spent == pytest.approx(expected)


def test_a_mistral_model_nobody_listed_still_needs_the_mistral_key(tmp_path):
    from app import modelcatalogue

    assert modelcatalogue.provider_for("mistral-unlisted-9", tmp_path) == "mistral"
    assert modelcatalogue.provider_for("gpt-4o-mini", tmp_path) == "openai"


def test_a_key_saved_for_the_agent_does_not_make_the_paid_plane_look_runnable(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY",
                 "EXA_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / "env"
    env.write_text("EXA_API_KEY=x\nMISTRAL_API_KEY=y\n", encoding="utf-8")
    path = tmp_path / "app.sqlite"
    # Any key is still the answer to "are the keys in".
    from app import keys

    assert keys.ready(env)
    # The default model is OpenAI's, and there is no OpenAI key.
    assert not prefs.paid_plane_ready(path, env)
    conn = state.connect(path)
    try:
        prefs.write(conn, {prefs.MODEL: "mistral-small-latest"})
    finally:
        conn.close()
    assert prefs.paid_plane_ready(path, env)


class _Recorder:
    def __init__(self):
        self.job_id = "job-1"
        self.lines: list[str] = []

    def set(self, fraction, message=""):
        self.lines.append(message)

    def log(self, message):
        self.lines.append(message)

    def check(self):
        pass


@pytest.mark.parametrize("outcome", ["uncounted", "failed"])
def test_a_billed_row_nobody_could_count_spends_the_agendas_ceiling(
    tmp_path, monkeypatch, outcome,
):
    from app import agenda
    from app.web.settings import Settings

    monkeypatch.setattr(agenda, "compute", lambda *a, **k: {"rows": [
        {"kind": "empty_subject", "subject_id": one, "pack_id": "probe"}
        for one in ("s1", "s2", "s3")], "note": ""})
    ran = []

    def research(settings, params, progress):
        ran.append(params["budget_usd"])
        if outcome == "failed":
            raise RuntimeError("Mistral is over quota (429)")
        return {"spent_usd": None}

    monkeypatch.setattr(tasks, "research", research)
    progress = _Recorder()
    result = tasks.agenda_run(Settings(
        store_path=tmp_path / "k.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl"), {"backend": "api"}, progress)
    # One row, then the walk stops: adding nothing would have billed all three.
    assert ran == [tasks.DEFAULT_AGENDA_BUDGET_USD]
    assert result["stopped"] == "budget"
    assert result["spent_usd"] == pytest.approx(tasks.DEFAULT_AGENDA_BUDGET_USD)
    assert any("cost unknown" in line for line in progress.lines)
