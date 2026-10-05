"""The local asker's own legwork: queries, then pages read together.

No model and no network: the plan, the search, the fetcher and the reader are
stubs built here, exactly as the local plane's tests build theirs. What is
under test is the orchestration - which queries are kept, which pages are
read, what the model is handed, and what happens when a page will not read.
"""

import threading

import pytest

from app.providers import local_agent
from app.providers.local_inference import LocalInferenceError


@pytest.fixture(autouse=True)
def short_pages_count(monkeypatch):
    """The stub pages here are a few words; a real page is not."""
    monkeypatch.setattr(local_agent, "MIN_PAGE_CHARS", 0)


class Plan:
    """The socket that proposes queries; scripted per test."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class Complete:
    def __init__(self, reply: str = ""):
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


def searcher(hits, started=None, gate=None):
    def search(query, limit):
        if started is not None:
            started.append(query)
        if gate is not None:
            gate()
        return hits[:limit]
    return search


def reader(texts):
    def fetch(url):
        return texts.get(url, "")
    return fetch


def make(plan_reply, hits, texts, **over):
    plan = Plan(plan_reply)
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete, searcher(hits), reader(texts),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    return asker, plan, complete


def test_pages_are_named_in_the_prompt_with_their_urls():
    asker, _, complete = make(
        '["q1", "q2"]',
        [{"url": "https://a.test/1", "title": "A"},
         {"url": "https://a.test/2", "title": "B"}],
        {"https://a.test/1": "alpha text", "https://a.test/2": "beta text"})
    asker.ask("what goes wrong with the widget")
    assert "https://a.test/1" in complete.prompts[0]
    assert "alpha text" in complete.prompts[0]
    assert "https://a.test/2" in complete.prompts[0]


def test_an_unreadable_page_is_a_miss_not_a_failure():
    asker, _, complete = make(
        '["q1"]',
        [{"url": "https://a.test/gone", "title": "G"},
         {"url": "https://a.test/here", "title": "H"}],
        {"https://a.test/here": "the only readable page"})
    asker.ask("widget problems")
    assert "the only readable page" in complete.prompts[0]
    assert "https://a.test/gone" not in complete.prompts[0]


def test_a_raising_fetcher_is_a_miss_not_a_crash():
    def broken(url):
        raise RuntimeError("connection reset")
    plan = Plan('["q1"]')
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete, searcher([{"url": "https://a.test/x", "title": "X"}]),
        broken, model="m", search_provider="stub")
    asker.on_action = lambda line: None
    with pytest.raises(LocalInferenceError):
        asker.ask("widget problems")


def test_duplicate_queries_are_searched_once():
    asked: list[str] = []
    plan = Plan('["widget problems", "Widget Problems", " " , "widget faults"]')
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete,
        searcher([{"url": "https://a.test/1", "title": "A"}],
                 started=asked),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert len(asked) == 2


def test_pages_are_read_side_by_side_not_one_after_another():
    lock = threading.Lock()
    inside = []
    released = threading.Event()

    def gate():
        with lock:
            inside.append(1)
        if len(inside) >= 2:
            released.set()
        assert released.wait(5.0), "pages were fetched one at a time"

    plan = Plan('["q"]')
    complete = Complete()
    def fetch(url):
        gate()
        return f"text {url.rsplit('/', 1)[-1]}"

    asker = local_agent.LocalAsker(
        plan, complete,
        searcher([{"url": f"https://a.test/{i}", "title": str(i)}
                  for i in range(local_agent.MAX_PAGES)]),
        fetch,
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert len(complete.prompts) == 1


def test_the_searches_go_out_together():
    """Three queries, three searches in flight at once, not one by one."""
    inside: list[int] = []
    lock = threading.Lock()
    all_in = threading.Event()

    def gate():
        with lock:
            inside.append(1)
            if len(inside) >= 3:
                all_in.set()
        assert all_in.wait(5.0), "searches ran one at a time"

    plan = Plan('["q1", "q2", "q3"]')
    asker = local_agent.LocalAsker(
        plan, Complete(),
        searcher([{"url": "https://a.test/1", "title": "A"}], gate=gate),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert len(inside) == 3


def test_a_page_that_never_answers_does_not_hold_the_run(monkeypatch):
    """The slow page is abandoned at the deadline; the others are read."""
    monkeypatch.setattr(local_agent, "READ_DEADLINE", 0.5)
    stuck = threading.Event()
    said: list[str] = []

    def fetch(url):
        if url.endswith("/slow"):
            stuck.wait(10.0)
            return "too late"
        return "the readable page"

    asker = local_agent.LocalAsker(
        Plan('["q"]'), Complete(),
        searcher([{"url": "https://a.test/slow", "title": "S"},
                  {"url": "https://a.test/fast", "title": "F"}]),
        fetch, model="m", search_provider="stub")
    asker.on_action = said.append
    import time
    started = time.monotonic()
    asker.ask("widget")
    stuck.set()
    assert time.monotonic() - started < 5.0
    assert list(asker.sources) == ["https://a.test/fast"]
    assert any("slow page" in line for line in said)


def test_a_long_page_is_cut_around_the_queries_not_from_the_top():
    """The window a small model reads is the page's part about the subject.

    The kept text is also what the quotes are checked against, so a quote
    from the part the model never saw is still refused.
    """
    menu = "\n\n".join(f"Menu entry number {i} of the site" for i in range(400))
    page = ("Widget page\n\n" + menu
            + "\n\nThe widget gearbox fails at 60 000 km, owners report.")
    asker = local_agent.LocalAsker(
        Plan('["widget gearbox fails"]'), Complete(),
        searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": page}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    kept = asker.sources["https://a.test/1"]
    assert len(kept) <= local_agent.PAGE_CHARS
    assert "gearbox fails at 60 000 km" in kept
    assert kept.startswith("Widget page")


def test_a_stub_page_is_a_miss_and_a_spare_takes_its_place(monkeypatch):
    """A cookie wall or an 'access denied' is not one of the pages read."""
    monkeypatch.setattr(local_agent, "MIN_PAGE_CHARS", 80)
    monkeypatch.setattr(local_agent, "MAX_PAGES", 1)
    asker = local_agent.LocalAsker(
        Plan('["q"]'), Complete(),
        searcher([{"url": "https://a.test/wall", "title": "W"},
                  {"url": "https://a.test/real", "title": "R"}]),
        reader({"https://a.test/wall": "Access denied",
                "https://a.test/real": "A real page. " * 30}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert list(asker.sources) == ["https://a.test/real"]
