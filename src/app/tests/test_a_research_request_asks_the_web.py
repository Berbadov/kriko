"""A request for researched, sourced answers becomes a web turn.

The reader's sentence, from a 0.3.8 field run: *"Fiat Egea'da en sık
karşılaşılan sorunları güvenilir kaynaklardan araştır"*. Two defects met on it:

* the router only knew the English "search the web" shapes, so an explicit
  research request went to ordinary chat and Codex answered from memory
  ("this session has no web search or page-opening tool");
* in ordinary chat a tool-less CLI is asked for a `SEARCH:` line and, in the
  same prompt, told it has no tools of any kind and must answer at once. The
  model that obeyed the note refused, which is what the reader reported.

The first is fixed where the routes are decided; the second where the note is
appended, so it holds for every brief that offers the written request.
"""

# ruff: noqa: F811 — `ctx` is a fixture imported from test_chat_turn, so each test redefines it by name.

import pytest

from app import chat
from app.providers import harness
from app.providers.harness import HarnessResearcher
from app.tests.harness_fixtures import row
from app.tests.test_chat_turn import Script, ctx  # noqa: F401 — `ctx` is a shared fixture


@pytest.mark.parametrize("message", [
    "Fiat Egea'da en sık karşılaşılan sorunları güvenilir kaynaklardan araştır",
    "Fiat Egea'nın bilinen sorunlarını internetten araştır",
    "Fiat Egea için kullanıcı şikayetlerini web'de araştır",
    "Research the Fiat Egea's common problems from reliable sources on the web",
    "Look up owner reports on the internet for the Fiat Egea",
])
def test_an_explicit_research_request_routes_to_the_web(message):
    assert chat.route_message(message) == "web"


@pytest.mark.parametrize("message", [
    "Merhaba, nasılsın?",
    "What does a turbo do?",
    "Fiat Egea'nın bilinen sorunları neler?",
    "Explain what a turbo does in one line",
])
def test_an_ordinary_or_record_question_does_not_become_a_web_turn(message):
    assert chat.route_message(message) in {"chat", "catalogue"}


def test_the_field_sentence_searches_the_web(ctx):
    searched = []

    def search(query, limit):
        searched.append(query)
        return [{"title": "Owner thread", "site": "forum.example",
                 "url": "https://forum.example/fiat-egea"}]

    ctx.web_search = search
    ctx.web_read = lambda url: "EGR valve clogging on 1.3 MultiJet diesels is widely reported."
    agent = Script("The EGR valve clogs. [https://forum.example/fiat-egea]")

    out = chat.run_turn(
        "Fiat Egea'da en sık karşılaşılan sorunları güvenilir kaynaklardan araştır",
        ask=agent, ctx=ctx)

    assert searched, "the web turn never ran"
    assert out["search_rounds"] == 1
    assert out["steps"][0]["source"] == "web_search"
    assert "https://forum.example/fiat-egea" in out["sources"]


def test_a_bare_product_name_asks_for_research_before_answering():
    brief = chat.chat_brief("fiat egea", [])

    assert "only a product's name" in brief
    assert "do not answer from memory" in brief
    assert "known problems and common" in brief


def test_the_toolless_note_keeps_the_search_the_brief_asked_for():
    brief = chat.chat_brief("What changed in the latest Python release?", [])
    note = harness.toolless_note(brief)

    assert "SEARCH:" in note
    assert "no tools of any kind" in note
    assert "Kriko runs the search" in note


def test_a_brief_that_asks_for_no_search_keeps_the_plain_note():
    note = harness.toolless_note("Read the pages below and report the risks.")

    assert note == harness.TOOLLESS_NOTE
    assert "SEARCH:" not in note


def test_a_toolless_harness_ask_carries_the_search_note(monkeypatch):
    researcher = HarnessResearcher(row("codex"))
    prompts: list[str] = []
    monkeypatch.setattr(
        researcher, "_run",
        lambda prompt: prompts.append(prompt) or "SEARCH: fiat egea common problems")

    reply = researcher.ask(chat.chat_brief("Fiat Egea sorunları neler?", []),
                           allow_tools=False)

    assert reply.startswith("SEARCH:")
    assert prompts[0].endswith(harness.TOOLLESS_SEARCH_NOTE)


def test_an_ordinary_toolless_ask_carries_the_plain_note(monkeypatch):
    researcher = HarnessResearcher(row("codex"))
    prompts: list[str] = []
    monkeypatch.setattr(researcher, "_run", lambda prompt: prompts.append(prompt) or "ok")

    researcher.ask("Read the pages below and report the risks.", allow_tools=False)

    assert prompts[0].endswith(harness.TOOLLESS_NOTE)
