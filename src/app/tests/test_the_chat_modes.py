"""Chat can be asked to do more than "find me one": alternatives, the cheapest, the merchants.

The reader's words: *"we also need more modes like find alternatives, find the
cheapest, search the provider"*, and of the last: *"like in Amazon same product
is sold by many merchants, the quality of those merchants I meant."* A mode is
a buying turn with its own question to the agent and one more search shaped for
it. It is picked by a chip or by the words of the message, and it never loosens
the evidence rules a buying turn already has.
"""

import dataclasses
import functools

import pytest

from app import chat, chatdata, exactfind
from app.web import state


@pytest.fixture
def ctx(tmp_path):
    from kriko.store.db import connect

    store = connect(tmp_path / "knowledge.sqlite")
    app_state = state.connect(tmp_path / "app.sqlite")
    yield chatdata.Context(store=store, app=app_state)
    store.close()
    app_state.close()


class Script:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


WEB_ROWS = [{
    "url": "https://shop.example/battery", "title": "Battery", "page_read": True,
    "source_trust": {"label": "a battery shop", "domain": "shop.example"},
}]


def _web(monkeypatch):
    """A web source that keeps the arguments it was called with."""
    calls: list[dict] = []
    original = chatdata.SOURCES["web_search"]

    @functools.wraps(original.run)
    def run(ctx, **kwargs):
        calls.append(kwargs)
        return {"rows": WEB_ROWS, "truncated": False, "note": ""}

    monkeypatch.setitem(chatdata.SOURCES, "web_search", dataclasses.replace(original, run=run))
    return calls


# ── what the words ask for ──────────────────────────────────────────────

@pytest.mark.parametrize("message, mode", [
    ("cheapest Bosch S4 car battery", "cheapest"),
    ("Golf 5 icin en ucuz kis lastigi", "cheapest"),
    ("alternatives to the Sony WH-1000XM5", "alternatives"),
    ("what are the alternatives to the Sony WH-1000XM5", "alternatives"),
    ("muadil Bosch S4 aku", "alternatives"),
    ("which sellers of Nike Pegasus 41 can I trust", "merchants"),
    ("who sells 205/55 R16 winter tyres", "merchants"),
    ("iPhone 15 saticisi guvenilir mi", "merchants"),
])
def test_the_words_of_a_message_can_ask_for_a_mode(message, mode):
    assert chat.detect_mode(message) == mode


@pytest.mark.parametrize("message", [
    "what is the cheapest planet",
    "alternatives to Python",
    "explain alternatives in React 18",
    "I want an explanation of cheapest path algorithms",
    "tell me a joke",
])
def test_a_word_alone_does_not_turn_a_question_into_shopping(message):
    assert chat.detect_mode(message) == ""


def test_a_follow_up_after_a_web_answer_may_ask_for_a_mode():
    history = [{"role": "agent", "text": "…", "sources": ["web_search"]}]
    assert chat.detect_mode("any other alternatives?", history) == "alternatives"
    assert chat.detect_mode("any other alternatives?") == ""


def test_a_pressed_chip_wins_over_the_words_and_a_wrong_chip_is_ignored():
    assert chat.mode_of("cheapest Bosch S4", "merchants") == "merchants"
    assert chat.mode_of("Bosch S4 battery", "cheapest") == "cheapest"
    assert chat.mode_of("cheapest Bosch S4", "no-such-mode") == "cheapest"
    assert chat.mode_of("tell me a joke", "no-such-mode") == ""


# ── what a mode turn does ───────────────────────────────────────────────

@pytest.mark.parametrize("mode, marker", [
    ("alternatives", "MODE: ALTERNATIVES"),
    ("cheapest", "MODE: CHEAPEST"),
    ("merchants", "MODE: MERCHANTS"),
])
def test_a_mode_turn_searches_the_web_as_a_buying_turn_with_the_modes_rules(
        ctx, monkeypatch, mode, marker):
    calls = _web(monkeypatch)
    answering = Script("[Battery](https://shop.example/battery) 100 EUR")
    # Words with no shopping intent in them: only the chip makes this a mode turn.
    out = chat.run_turn("Bosch S4", ask=answering, ctx=ctx, mode=mode)
    assert calls[0]["buying"] == "yes" and calls[0]["mode"] == mode
    brief = answering.prompts[-1]
    assert marker in brief
    assert "THE READER WANTS SOMETHING TO BUY" in brief  # the buying rules still hold
    assert "LINKS ARE REQUIRED" in brief
    assert out["mode"] == mode
    assert "shop.example/battery" in out["answer"]


def test_the_merchant_rules_judge_the_seller_by_what_the_page_shows():
    brief = chat.web_answer_brief("who sells Bosch S4", [], WEB_ROWS, "", buying=True,
                                  mode="merchants")
    assert "seller_signals" in brief and "the page says" in brief
    assert "Say 'nothing shown'" in brief


def test_the_cheapest_rules_compare_one_exact_product_and_flag_a_doubtful_seller():
    brief = chat.web_answer_brief("cheapest Bosch S4", [], WEB_ROWS, "", buying=True,
                                  mode="cheapest")
    assert "same exact product" in brief
    assert "red flag" in brief
    assert "one price is not a comparison" in brief


def test_a_turn_without_a_mode_carries_no_mode_rules(ctx, monkeypatch):
    calls = _web(monkeypatch)
    answering = Script("Michelin Alpin 6 fits.")
    out = chat.run_turn("I need winter tires for my Golf 5", ask=answering, ctx=ctx)
    assert "mode" not in calls[0]
    assert "MODE:" not in answering.prompts[-1]
    assert out["mode"] == ""


def test_a_plain_question_with_a_word_that_is_not_a_request_gets_no_mode(ctx, monkeypatch):
    calls = _web(monkeypatch)
    answering = Script("Mercury, by a long way.")
    out = chat.run_turn("explain alternatives in React 18", ask=answering, ctx=ctx)
    assert out["mode"] == ""
    assert all("mode" not in call for call in calls)


# ── the extra search ────────────────────────────────────────────────────

def test_a_mode_adds_one_search_and_keeps_a_share_of_both(ctx):
    seen: list[str] = []

    def search(query, cap):
        seen.append(query)
        tag = "extra" if query.endswith("seller reviews") else "first"
        return [{"url": f"https://{tag}{n}.example/p", "title": f"{tag} {n}"} for n in range(8)]

    ctx = dataclasses.replace(ctx, web_search=search, web_read=None)
    out = chatdata.run("web_search", ctx, {"query": "Bosch S4 battery", "buying": "yes",
                                           "mode": "merchants"})
    assert seen[0] == "Bosch S4 battery"
    assert seen.count("Bosch S4 battery seller reviews") == 1
    hosts = {row["url"].split("//")[1][:5] for row in out["rows"]}
    assert hosts == {"first", "extra"}  # the cap of 8 did not fill with the first search


def test_a_failed_mode_search_leaves_the_first_search_standing(ctx):
    def search(query, cap):
        if query.endswith("price"):
            raise RuntimeError("the search engine is down")
        return [{"url": "https://a.example/p", "title": "A"}]

    ctx = dataclasses.replace(ctx, web_search=search, web_read=None)
    out = chatdata.run("web_search", ctx, {"query": "Bosch S4", "buying": "yes", "mode": "cheapest"})
    assert [row["url"] for row in out["rows"]] == ["https://a.example/p"]


def test_the_mode_words_follow_the_language_of_the_question():
    assert exactfind.mode_query("Golf 5 kis lastigi", "cheapest", "tr") == "Golf 5 kis lastigi fiyat"
    assert exactfind.mode_query("Golf 5 tyres", "alternatives") == "Golf 5 tyres alternatives"
    assert exactfind.mode_query("anything", "no-such-mode") == ""
