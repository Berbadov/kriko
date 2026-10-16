"""A run does not wait on one search at a time, nor on pages that are dead.

Measured on a Vibe quick look (66 s): three searches in a row cost 20 s, and two
dead pages held the page read for 16 s each while the places they would have
filled stayed empty.
"""

import threading
import time

import pytest

from app.providers import local_agent
from app.providers.local_inference import LocalInferenceError
from app.tests.test_local_agent import Complete, Plan, reader


class Engines:
    """A search that names its engines and records who was asked what, and when."""

    def __init__(self, names, answers=None, delay=0.0):
        self.engines = list(names)
        self.calls: list[tuple[str, str]] = []
        self.inside: dict[str, int] = {}
        self.most_per_engine = 0
        self.answers = answers or {}
        self.delay = delay
        self.lock = threading.Lock()
        self.check_cancelled = None

    def __call__(self, query, limit=5, engines=""):
        asked = engines or ",".join(self.engines)
        with self.lock:
            self.calls.append((query, asked))
            for name in asked.split(","):
                self.inside[name] = self.inside.get(name, 0) + 1
                self.most_per_engine = max(self.most_per_engine, self.inside[name])
        time.sleep(self.delay)
        with self.lock:
            for name in asked.split(","):
                self.inside[name] -= 1
        hit = self.answers.get((query, asked),
                               self.answers.get(query, [{"url": f"https://a.test/{query}",
                                                         "title": query}]))
        return hit


def _asker(search, pages):
    asker = local_agent.LocalAsker(
        Plan('["q1", "q2", "q3"]'), Complete(), search, reader(pages),
        model="m", search_provider="openserp")
    asker.on_action = lambda line: None
    return asker


PAGES = {f"https://a.test/q{i}": "a readable page of text, long enough. " * 4
         for i in (1, 2, 3)}


def test_each_query_goes_to_its_own_engine_at_the_same_time():
    search = Engines(["google", "duckduckgo", "bing"], delay=0.3)
    started = time.monotonic()

    _asker(search, PAGES).ask("widget")

    assert time.monotonic() - started < 0.8  # three in a row would be 0.9 s of searching
    assert sorted(asked for _q, asked in search.calls) == ["bing", "duckduckgo", "google"]
    assert search.most_per_engine == 1  # no engine is asked two at once


def test_a_query_whose_engine_came_back_empty_is_asked_of_every_engine():
    search = Engines(["google", "duckduckgo", "bing"],
                     answers={("q3", "bing"): []})

    _asker(search, PAGES).ask("widget")

    again = [asked for query, asked in search.calls if query == "q3"]
    assert again == ["bing", "google,duckduckgo,bing"]


def test_a_service_that_is_down_is_not_retried_query_by_query():
    from kriko.research.politeness import LocalSearchError

    class Down(Engines):
        def __call__(self, query, limit=5, engines=""):
            super().__call__(query, limit, engines)
            raise LocalSearchError("down")

    search = Down(["google", "duckduckgo", "bing"])

    with pytest.raises(LocalInferenceError):
        _asker(search, PAGES).ask("widget")

    assert len(search.calls) == 3


def test_a_search_with_one_engine_is_still_asked_one_query_at_a_time():
    search = Engines(["google"], delay=0.05)

    _asker(search, PAGES).ask("widget")

    assert search.most_per_engine == 1
    assert [asked for _q, asked in search.calls] == ["google", "google", "google"]


@pytest.mark.parametrize("quick", [False, True])
def test_more_queries_than_engines_never_overlap_the_same_engine(quick):
    queries = ["q1", "q2", "q3", "q4", "q5"]
    search = Engines(["google", "bing"], delay=0.05)
    pages = {f"https://a.test/{query}": f"Page about {query}. " * 15
             for query in queries}

    _asker(search, pages)._read(queries, quick=quick)

    assert len(search.calls) == len(queries)
    assert search.most_per_engine == 1
    assert {asked for _query, asked in search.calls} == {"google", "bing"}


def test_spares_are_read_beside_pages_that_do_not_answer(monkeypatch):
    monkeypatch.setattr(local_agent, "HEDGE_AFTER", 0.2)
    monkeypatch.setattr(local_agent, "READ_DEADLINE", 5.0)
    dead = threading.Event()
    urls = [f"https://site{i}.test/p{i}" for i in range(1, 6)]

    def fetch(url):
        if url in urls[:3]:
            dead.wait(3.0)  # the first three never answer in time
            return ""
        return f"page {url}: a readable page of text, long enough. " * 4

    asker = local_agent.LocalAsker(
        Plan('["q"]'), Complete(),
        lambda query, limit=5: [{"url": url, "title": "t"} for url in urls],
        fetch, model="m", search_provider="openserp")
    asker.on_action = lambda line: None
    asker.max_pages = 2
    started = time.monotonic()
    try:
        pages = asker._read(["q"])
    finally:
        dead.set()

    assert len(pages) == 2
    assert time.monotonic() - started < 2.0  # not the 3 s the dead pages hold
