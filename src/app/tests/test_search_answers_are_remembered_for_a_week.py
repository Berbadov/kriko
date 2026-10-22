"""A search answer is reused for a week, and a look can be given a quota.

Free search endpoints challenge an address after a handful of queries, so the
two behaviours that matter are: the same question is not paid for twice, and a
single look cannot spend an unbounded number of them. A failure is never kept.
"""

from __future__ import annotations

import pytest

from app.providers import searchcache

HITS = [{"url": "https://example.com/a", "title": "A", "site": "test"}]


def counting(hits: list[dict] | None = None):
    asked: list[str] = []

    def search(query: str, limit: int = 5) -> list[dict]:
        asked.append(query)
        return list(hits if hits is not None else HITS)

    search.asked = asked
    return search


def test_the_same_question_is_asked_once(tmp_path) -> None:
    inner = counting()
    search = searchcache.cached(inner, path=tmp_path / "cache.sqlite")

    first = search("dyson trigger", 4)
    second = search("dyson trigger", 4)

    assert first == second == HITS
    assert inner.asked == ["dyson trigger"]


def test_a_different_limit_is_a_different_question(tmp_path) -> None:
    inner = counting()
    search = searchcache.cached(inner, path=tmp_path / "cache.sqlite")

    search("dyson trigger", 4)
    search("dyson trigger", 8)

    assert inner.asked == ["dyson trigger", "dyson trigger"]


def test_an_expired_answer_is_asked_again(tmp_path) -> None:
    inner = counting()
    search = searchcache.cached(inner, path=tmp_path / "cache.sqlite", ttl=0)

    search("dyson trigger", 4)
    search("dyson trigger", 4)

    assert inner.asked == ["dyson trigger", "dyson trigger"]


def test_a_budget_stops_a_new_question_but_not_a_remembered_one(tmp_path) -> None:
    inner = counting()
    search = searchcache.cached(inner, path=tmp_path / "cache.sqlite", budget=1)

    search("first question", 4)
    assert search("first question", 4) == HITS
    with pytest.raises(searchcache.BudgetExhausted, match="one more"):
        search("second question", 4)
    assert inner.asked == ["first question"]


def test_a_failure_is_not_remembered(tmp_path) -> None:
    asked: list[str] = []

    def failing(query: str, limit: int = 5) -> list[dict]:
        asked.append(query)
        if len(asked) == 1:
            raise searchcache.BudgetExhausted("the engine said no")
        return HITS

    search = searchcache.cached(failing, path=tmp_path / "cache.sqlite")

    with pytest.raises(searchcache.BudgetExhausted):
        search("dyson trigger", 4)
    assert search("dyson trigger", 4) == HITS
    assert asked == ["dyson trigger", "dyson trigger"]
