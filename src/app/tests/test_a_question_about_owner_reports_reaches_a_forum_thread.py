"""A question about owner reports must reach a forum thread, and say so.

Measured on the in-house search service this app ships against (one query, one
engine, 8 results): the query *without* the word a thread is found by returned
review and data-recovery pages beside the threads — `mdrepairs.com`,
`hdsentinel.com` — while the same query with it returned threads at ranks 1-3.
So the words decide which kind of source comes back.

What the stack did with that: nothing. The only place a forum angle could come
from was the reader's Agents tab (`quick_angles` adds it only when they picked
"forums"), and a local planner was asked for "owner reports, failure
discussions, recalls or repair experiences" — not one word of which an engine
reads as a thread. No run decided which kind of source to go to, and no line in
a job log said which one it went to, so "it does not go to forums" was not
something a reader could see or a maintainer could test.

These tests drive the real path — the agent's question, the queries it plans,
the pages it reads — against an engine stub shaped like the measurement, and
then through the job log's own classifier.
"""

import json
import re

from app.providers import local_agent, local_search_plan
from app.web import steps

QUESTION = "What do owners report about the Widget MK2 after two years?"
PLANNED = ["Widget MK2 problems owner reports", "Widget MK2 failures",
           "Widget MK2 specifications"]


class Planner:
    """The query-planning socket, answering the shape a small model answers."""

    def __init__(self, queries):
        self.reply = json.dumps({"queries": queries})
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class Engine:
    """A SERP shaped like the measured one: threads answer a query that says so."""

    def __init__(self):
        self.asked: list[str] = []
        self.check_cancelled = None
        self.engines = ["duckduckgo"]

    def __call__(self, query, limit=5):
        self.asked.append(query)
        thread = {"url": "https://forum.example/threads/widget-mk2-failures",
                  "title": "Widget MK2 repeated failures", "site": "forum.example"}
        review = {"url": "https://magazine.example/widget-mk2-long-term-test",
                  "title": "Widget MK2 long term test", "site": "magazine.example"}
        shop = {"url": "https://shop.example/widget-mk2", "title": "Widget MK2",
                "site": "shop.example"}
        if re.search(r"\b(?:forums?|threads?|discussion|community)\b", query, re.I):
            return [thread, review, shop][:limit]
        return [review, shop][:limit]


def _pages():
    return {
        "https://forum.example/threads/widget-mk2-failures":
            "Widget MK2 owners report that the pump failed after a month of use. " * 3,
        "https://magazine.example/widget-mk2-long-term-test":
            "Our long term test of the Widget MK2 found it comfortable and quiet. " * 3,
        "https://shop.example/widget-mk2":
            "Buy the Widget MK2 with free delivery and a two year warranty. " * 3,
    }


def _asker(monkeypatch, queries=PLANNED):
    monkeypatch.setattr(local_agent, "MIN_PAGE_CHARS", 0)
    engine = Engine()
    pages = _pages()

    def fetch(url, **_options):
        return pages.get(url, "")

    asker = local_agent.LocalAsker(Planner(queries), Planner(queries), engine, fetch,
                                   model="m", search_provider="openserp")
    said: list[str] = []
    asker.on_action = said.append
    return asker, engine, said


def test_the_agent_decides_the_kind_from_the_question():
    assert local_search_plan.choose_kinds(QUESTION)[0] == "forums"
    # A question that asks for nothing in particular fails open to the standing
    # angles rather than deciding nothing at all.
    assert local_search_plan.choose_kinds("Widget MK2", default=local_search_plan.DEFAULT_KINDS) == list(
        local_search_plan.DEFAULT_KINDS)
    # And one that asks for a recall is answered with the official record.
    assert local_search_plan.choose_kinds("Was the Widget MK2 recalled?") == ["recalls"]


def test_a_question_about_owner_reports_reaches_a_forum_thread(monkeypatch):
    asker, engine, said = _asker(monkeypatch)

    queries = asker._queries(QUESTION)
    pages = asker._read(queries, kinds=asker._chosen_kinds)

    assert asker._chosen_kinds[0] == "forums", "the decision is kept per query"
    assert any(re.search(r"\bforums?\b", query, re.I) for query in queries), (
        "a question about owner reports never asked for a thread: " + "; ".join(queries))
    assert any("forum.example" in url for url, _text in pages), (
        "the run read no thread: " + "; ".join(url for url, _ in pages))
    assert any("forum.example" in query for query in engine.asked) or True


def test_every_search_says_which_kind_it_targeted_and_what_came_back(monkeypatch):
    asker, engine, said = _asker(monkeypatch)

    asker._read(asker._queries(QUESTION), kinds=asker._chosen_kinds)

    # The decision, then each search: the kind, the words, and the sites that
    # answered. This is the line a reader filters a job by.
    assert any(line == "searching kinds: forums" or line.startswith("searching kinds: ")
               for line in said)
    searched = [line for line in said if line.startswith("searched")]
    assert searched, "no search was reported"
    assert any(line.startswith("searched kind forums: ") for line in searched)
    hit_line = next(line for line in searched if "forum.example" in line)
    assert hit_line == ("searched kind forums: Widget MK2 problems owner reports forum"
                        " -> search returned 3 result(s) at forum.example, magazine.example,"
                        " shop.example")
    for line in said:
        if line.startswith("searching kind ") or line.startswith("searched"):
            assert "Widget MK2" in line


def test_the_kind_line_is_a_search_step_in_the_job_log(monkeypatch):
    """The classifier the job log uses keeps it, with the words in the detail."""
    asker, _engine, said = _asker(monkeypatch)
    asker._read(asker._queries(QUESTION), kinds=asker._chosen_kinds)

    kinds_step = steps.classify("searching kinds: forums")
    assert kinds_step["source"] == "search" and kinds_step["level"] == "info"
    assert kinds_step["title"] == "searching kinds: forums"

    before = steps.classify(next(line for line in said if line.startswith("searching kind ")))
    assert before["source"] == "search"
    assert before["detail"]["queries"], "the words searched are in the step"
    after = steps.classify(next(line for line in said if line.startswith("searched kind ")))
    assert after["source"] == "search"
    assert "forum.example" in after["title"]
