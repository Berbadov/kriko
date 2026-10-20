"""The question comes before the spend, and it carries buttons.

The reader's report: *"i ask i need winter tires for my golf 5, agent must ask
(every agent) what's your sizes?"* The answer they got asked which Golf it was
in the middle of a long prose reply, after the search had already been paid for
and in words they could not answer with a click. So a turn now asks one
question first, with two to six short options, on the agent the reader chose;
the answer to it is their next message, which makes a chain of two questions
two turns rather than an interrogation inside one.

Everything here is deliberately fail-open: a question that cannot be read, has
nothing to click, or an agent that errors is the turn going on to its answer.
A question must never cost the reader the answer behind it.
"""

import dataclasses
import functools
import json

import pytest

from app import chat, chatdata
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
    """A fake agent: each call returns the next scripted reply and keeps the prompt."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("the agent was asked more often than the budget allows")
        return self.replies.pop(0)


def _ask(ask: str, *options: str, key: str = "size", why: str = "it changes the answer") -> str:
    return json.dumps({"ask": ask, "options": list(options), "key": key, "why": why})


def _stub(monkeypatch, name, reply):
    """Replace one source's reader with a fixed answer, keeping its signature."""
    original = chatdata.SOURCES[name]

    @functools.wraps(original.run)
    def run(ctx, **kwargs):
        return dict(reply)

    monkeypatch.setitem(chatdata.SOURCES, name, dataclasses.replace(original, run=run))


WEB_ROWS = [{
    "url": "https://shop.example/winter-tyre",
    "title": "Winter tyre",
    "page_read": True,
    "source_trust": {"label": "a tyre shop", "domain": "shop.example"},
}]


# ── the question, its options, and what it is asked of ──────────────────

def test_a_missing_size_is_asked_before_anything_is_searched(ctx):
    asked = Script(_ask("Which tyre size is on the car?", "195/65 R15", "205/55 R16"))
    answering = Script("never reached")
    out = chat.run_turn("I need winter tires for my Golf 5", ask=answering,
                        clarify=asked, ctx=ctx)
    assert out["answer"] == ""
    assert out["questions"][0]["ask"] == "Which tyre size is on the car?"
    assert out["questions"][0]["options"] == ["195/65 R15", "205/55 R16"]
    assert answering.prompts == []
    # One quick call, and the reader's own words reached it.
    assert len(asked.prompts) == 1
    assert "READER'S MESSAGE: I need winter tires for my Golf 5" in asked.prompts[0]


def test_the_turn_asked_in_the_readers_saved_words(ctx):
    asked = Script(_ask("Which model year?", "2019", "2020"))
    chat.run_turn("I need winter tires", ask=Script("x"), clarify=asked, ctx=ctx,
                  preferences="Reader drives a 2020 Golf 5, 205/55 R16.")
    assert "2020 Golf 5" in asked.prompts[0]


def test_the_same_question_is_never_asked_twice(ctx, monkeypatch):
    _stub(monkeypatch, "web_search", {"rows": WEB_ROWS, "truncated": False, "note": ""})
    asked = Script(_ask("Which tyre size is on the car?", "195/65 R15", "205/55 R16"))
    answering = Script("Michelin Alpin 6 in 205/55 R16 fits.")
    history = [
        {"role": "reader", "text": "I need winter tires for my Golf 5"},
        {"role": "agent", "text": "Which tyre size is on the car?",
         "questions": [{"id": "size", "ask": "Which tyre size is on the car?",
                        "options": ["195/65 R15", "205/55 R16"], "key": "size"}]},
    ]
    out = chat.run_turn("205/55 R16 Michelin", ask=answering, clarify=asked, ctx=ctx,
                        history=history)
    # It was asked once, its repeat was dropped, and the turn answered.
    assert len(asked.prompts) == 1
    assert out.get("questions", []) == []
    assert out["answer"].startswith("Michelin Alpin 6 in 205/55 R16 fits.")


def test_a_second_question_may_follow_the_first(ctx):
    """A size, then a model year: one click each, in chain."""
    asked = Script(_ask("Which model year?", "2010", "2012", key="year"))
    history = [
        {"role": "reader", "text": "I need winter tires for my Golf 5"},
        {"role": "agent", "text": "Which tyre size is on the car?",
         "questions": [{"id": "size", "ask": "Which tyre size is on the car?",
                        "options": ["195/65 R15", "205/55 R16"], "key": "size"}]},
    ]
    out = chat.run_turn("205/55 R16 Michelin", ask=Script("never reached"),
                        clarify=asked, ctx=ctx, history=history)
    assert out["questions"][0]["ask"] == "Which model year?"
    assert out["questions"][0]["options"] == ["2010", "2012"]


def test_an_information_question_is_answered_never_interrogated(ctx):
    asked = Script(_ask("Which size?", "a", "b"))
    answering = Script("It is the tyre's width, profile and wheel size.")
    out = chat.run_turn("What does 205/55 R16 mean?", ask=answering,
                        clarify=asked, ctx=ctx)
    assert asked.prompts == []
    assert out.get("questions", []) == []
    assert "tyre's width" in out["answer"]


def test_a_question_with_nothing_to_click_is_not_a_question(ctx):
    asked = Script(json.dumps({"ask": "Which size?", "options": ["only one"]}))
    answering = Script("Here is the answer.")
    out = chat.run_turn("I need winter tires", ask=answering, clarify=asked, ctx=ctx)
    assert out["answer"] == "Here is the answer."


def test_an_unreadable_question_never_costs_the_answer(ctx):
    def broken(prompt: str) -> str:
        raise RuntimeError("the helper call failed")

    answering = Script("Here is the answer anyway.")
    out = chat.run_turn("I need winter tires", ask=answering, clarify=broken, ctx=ctx)
    assert out["answer"] == "Here is the answer anyway."


def test_options_are_bounded_and_deduplicated():
    found = chat.parse_clarify(json.dumps({
        "ask": "Which one?",
        "options": ["A", "a", "B", "C", "D", "E", "F", "G"],
        "key": "variant",
    }))
    assert found is not None
    assert found["options"] == ["A", "B", "C", "D", "E", "F"]
    assert found["id"] == "variant"


# ── the links a buying answer owes, whichever agent wrote it ────────────

def test_a_buying_answer_the_model_left_unlinked_gets_the_pages_it_read(ctx, monkeypatch):
    _stub(monkeypatch, "web_search", {"rows": WEB_ROWS,
                                      "truncated": False, "note": ""})
    answering = Script("Choose the Michelin Alpin 6 for winter.")
    out = chat.run_turn("I need winter tires for my Golf 5", ask=answering, ctx=ctx)
    assert "[Winter tyre](https://shop.example/winter-tyre)" in out["answer"]
    assert "Pages Kriko checked" in out["answer"]


def test_an_information_answer_is_not_given_a_shop_list(ctx, monkeypatch):
    _stub(monkeypatch, "web_search", {"rows": WEB_ROWS, "truncated": False, "note": ""})
    answering = Script("205/55 R16 means a 205 mm width and a 55% profile.")
    out = chat.run_turn("I need to understand tyre size 205/55 R16", ask=answering, ctx=ctx)
    assert "shop.example" not in out["answer"]


def test_product_only_mode_asks_for_a_list_not_an_essay(ctx, monkeypatch):
    _stub(monkeypatch, "web_search", {"rows": WEB_ROWS, "truncated": False, "note": ""})
    answering = Script("[Winter tyre](https://shop.example/winter-tyre) — 100 EUR")
    out = chat.run_turn("I need winter tires for my Golf 5", ask=answering, ctx=ctx,
                        product_only=True)
    brief = answering.prompts[-1]
    assert "PRODUCT-ONLY ANSWER" in brief
    assert "One line per product" in brief
    assert "shop.example" in out["answer"]


# ── what the thread keeps ───────────────────────────────────────────────

def test_a_question_is_kept_with_its_options(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        thread = state.create_chat_thread(conn)
        question = {"id": "size", "ask": "Which tyre size is on the car?",
                    "options": ["195/65 R15", "205/55 R16"], "key": "size",
                    "why": "it changes what fits"}
        state.add_chat_message(conn, thread["thread_id"], role="agent",
                               text=question["ask"], questions=[question])
        [stored] = state.chat_messages(conn, thread["thread_id"])
        assert stored["questions"] == [question]
        assert stored["text"] == question["ask"]
    finally:
        conn.close()


def test_the_answer_is_final_before_the_follow_ups_are_named(tmp_path, monkeypatch):
    """A complete answer must stop looking like a growing one at once.

    Naming the topic and its follow-ups is one more model call, and on a local
    model it can take several seconds. The reader's screen used to sit with the
    answer finished and its last words still fading for that whole time.
    """
    from app import chatmeta
    from app.web import tasks
    from app.web.jobs import Progress
    from app.web.settings import Settings

    paths = Settings(store_path=tmp_path / "knowledge.sqlite",
                     app_state_path=tmp_path / "app.sqlite",
                     analysis_log_path=tmp_path / "analysis.jsonl")

    class Completer:
        model = "local-test-model"

        def __call__(self, prompt):
            return "A short answer."

    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *a: Completer())
    seen: dict = {}

    def labels(ask, question, answer, **kwargs):
        # Whatever the job holds at this moment is what the screen is drawing.
        seen.update(state.get_job(conn, job_id)["result"] or {})
        return {"title": "", "followups": ["one more?"]}

    monkeypatch.setattr(chatmeta, "generate", labels)
    conn = state.connect(paths.app_state_path)
    try:
        thread = state.create_chat_thread(conn)
        reader = state.add_chat_message(conn, thread["thread_id"], role="reader", text="hello")
        job_id = state.create_job(conn, "chat_ask", {"thread_id": thread["thread_id"]})
        result = tasks.chat_ask(
            paths,
            {"thread_id": thread["thread_id"], "message_id": reader["message_id"],
             "text": "hello", "backend": "local"},
            Progress(job_id, conn),
        )
    finally:
        conn.close()

    assert result["answer"] == "A short answer."
    assert result["answer_final"] is True
    assert seen["answer"] == "A short answer."
    assert seen["answer_final"] is True
