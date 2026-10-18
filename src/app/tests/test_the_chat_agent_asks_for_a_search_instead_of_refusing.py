"""An agent that cannot browse asks Kriko to search; it never refuses.

A reader saw the agent say it had no web tools while Kriko searched their
sentence word for word. Two defects: an ordinary-chat agent was told to "say that
you need a web search" with no way to ask for one, and a web turn searched the
reader's sentence, filler and all. The agent now asks with one `SEARCH:` line,
and a web turn searches the words the agent wrote.
"""

# ruff: noqa: F811 — `ctx` is a fixture imported from test_chat_turn, so each test redefines it by name.

import pytest

from app import chat
from app.tests.test_chat_turn import Hooks, Script, ctx  # noqa: F401 — the shared fixtures


def _web(ctx, searched, rows=None):
    def search(query, limit):
        searched.append(query)
        if rows is None:
            return [{"title": "Result", "site": "maker.example",
                     "url": "https://maker.example/page"}]
        return rows(query)

    ctx.web_search = search
    ctx.web_read = lambda url: f"Page text for {url}."


@pytest.mark.parametrize("reply, words", [
    ("SEARCH: renault megane 4 1.5 dci oil", "renault megane 4 1.5 dci oil"),
    ("  `SEARCH: renault megane 4 oil`  ", "renault megane 4 oil"),
    ("**Search:** \"renault megane 4 oil\"", "renault megane 4 oil"),
    ("SEARCH: renault megane 4 oil\nSources: web_search", "renault megane 4 oil"),
])
def test_a_search_request_is_read_from_the_whole_reply(reply, words):
    assert chat.search_request(reply) == words


@pytest.mark.parametrize("reply", [
    "",
    "I would search for that, but here is what I know.",
    "SEARCH is a verb. It means to look for something.",
    "SEARCH: ",
    "SEARCH: a\nand then a long explanation\nof why",
    "Here you go.\nSEARCH: megane oil",
])
def test_an_answer_that_mentions_searching_is_an_answer(reply):
    assert chat.search_request(reply) == ""


def test_the_ordinary_prompt_offers_the_search_and_never_the_refusal():
    prompt = chat.chat_brief("What changed in the latest Python release?", [])

    assert "SEARCH:" in prompt
    assert "never say that you cannot search" in prompt
    assert "say that you need a web search" not in prompt


def test_an_agent_that_asks_for_a_search_gets_one_and_answers_from_it(ctx):
    searched = []
    _web(ctx, searched)
    agent = Script("SEARCH: python 3.14 release notes",
                   "Python 3.14 added deferred annotations. [https://maker.example/page]")
    hooks = Hooks()

    out = chat.run_turn("What changed in the newest python?", ask=agent, ctx=ctx, hooks=hooks)

    assert searched == ["python 3.14 release notes"]
    assert out["answer"].startswith("Python 3.14 added")
    assert out["agent_calls"] == 2
    assert out["steps"][0]["source"] == "web_search"
    assert out["steps"][0]["state"] == "done"
    assert "Page text for https://maker.example/page" in agent.prompts[1]
    assert "tell the reader that you cannot search the web" in agent.prompts[1]


def test_the_request_for_a_search_is_never_shown_as_the_answer(ctx):
    _web(ctx, [])
    agent = Script("SEARCH: python 3.14 release notes", "It added deferred annotations.")

    def ask_stream(prompt, on_text):
        reply = agent(prompt)
        on_text(reply)
        return reply

    hooks = Hooks()
    chat.run_turn("What changed in the newest python?", ask=agent, ask_stream=ask_stream,
                  ctx=ctx, hooks=hooks)

    shown = [one["answer"] for one in hooks.partials]
    assert shown and all(not text.startswith("SEARCH") for text in shown)


def test_a_web_turn_searches_the_words_the_agent_wrote(ctx):
    searched = []
    _web(ctx, searched)
    agent = Script("It is 5W-30. [https://maker.example/page]")
    quick = Script("megane 4 1.5 dci 2020 engine oil spec")

    out = chat.run_turn("Hey, could you please tell me which oil I should buy for my Megane 4?",
                        ask=agent, ask_quick=quick, ctx=ctx)

    assert searched == ["megane 4 1.5 dci 2020 engine oil spec"]
    assert out["agent_calls"] == 2
    assert "READER'S MESSAGE: Hey, could you please" in quick.prompts[0]


def test_a_follow_up_is_written_with_the_conversation_in_front_of_the_agent(ctx):
    searched = []
    _web(ctx, searched)
    history = [{"role": "reader", "text": "Which oil for a Megane 4?"},
               {"role": "agent", "text": "Several pages list 5W-30.", "sources": ["web_search"]}]
    quick = Script("megane 4 5w-30 oil price")

    chat.run_turn("Which one is cheaper?", ask=Script("Answer."), ask_quick=quick,
                  ctx=ctx, history=history)

    assert "Megane 4" in quick.prompts[0]
    assert searched == ["megane 4 5w-30 oil price"]


@pytest.mark.parametrize("broken", [
    lambda prompt: "",
    lambda prompt: "x" * 500,
    lambda prompt: (_ for _ in ()).throw(ValueError("the helper call failed")),
])
def test_an_unusable_search_line_falls_back_to_the_readers_own_words(ctx, broken):
    searched = []
    _web(ctx, searched)

    out = chat.run_turn("Find a quiet air purifier for a small bedroom",
                        ask=Script("Answer."), ask_quick=broken, ctx=ctx)

    assert searched == ["a quiet air purifier for a small bedroom"]
    assert out["answer"] == "Answer."


def test_a_page_the_reader_names_is_opened_not_rewritten(ctx):
    searched = []
    _web(ctx, searched)
    quick = Script()  # must never be asked

    chat.run_turn("What does https://maker.example/manual say about oil?",
                  ask=Script("It says 5W-30."), ask_quick=quick, ctx=ctx)

    assert quick.prompts == []


def test_written_words_that_find_nothing_are_retried_with_the_readers_own(ctx):
    searched = []
    _web(ctx, searched, rows=lambda q: [] if "obscure" in q else [
        {"title": "Result", "site": "maker.example", "url": "https://maker.example/page"}])
    quick = Script("obscure overly specific words")

    out = chat.run_turn("Find a quiet air purifier for a small bedroom",
                        ask=Script("Answer."), ask_quick=quick, ctx=ctx)

    assert searched == ["obscure overly specific words", "a quiet air purifier for a small bedroom"]
    assert [step["state"] for step in out["steps"]] == ["empty", "done"]


def test_a_search_with_no_results_tells_the_agent_to_say_so_and_not_to_refuse(ctx):
    _web(ctx, [], rows=lambda q: [])
    agent = Script("I found nothing today; from general knowledge it is 5W-30.")

    chat.run_turn("Find a quiet air purifier for a small bedroom", ask=agent, ctx=ctx)

    assert "If the results are empty or off the subject" in agent.prompts[0]
    assert "tell the reader that you cannot search the web" in agent.prompts[0]


def test_no_turn_spends_more_than_its_calls_on_searching(ctx):
    _web(ctx, [])
    agent = Script("SEARCH: python release", "Answer.")

    out = chat.run_turn("What changed in the newest python?", ask=agent,
                        ask_quick=Script("never used"), ctx=ctx)

    assert out["agent_calls"] <= chat.MAX_AGENT_CALLS

