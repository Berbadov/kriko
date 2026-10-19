"""The money ceiling cannot stop a run that is not spending money.

`ResearchTask.budget_usd` is a hard stop, and it works: `_charge` raises the
moment a run would spend past it. A subscription plane has no dollars to exceed
and could still run for an hour learning nothing, because every provider is
timing out one 45-second call at a time — the shape the 2026-10-18 sweep
recorded ("a 10-query run can spend 7.5 minutes learning nothing").

`ResearchTask.seconds` is that ceiling. It is checked between calls rather than
inside one (a request already in flight is not interrupted), and it raises the
same `BudgetExceeded` every caller already knows how to stop on — with a message
that says time, not money, so the run's own history does not lie about which
ceiling it hit.
"""

import time

import pytest

from kriko.research import ApiResearcher, BudgetExceeded, ResearchTask, STANDARD


class _Search:
    def __init__(self, delay: float = 0.0):
        self.calls = 0
        self.delay = delay

    def __call__(self, query, limit):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return [{"url": f"https://x.test/{self.calls}", "title": "t", "site": "x.test"}]


def _task(**over):
    base = dict(
        subject_id="s", subject_label="VW Golf", subject_kind="product",
        pack_id="org.test", identity={"make": "vw"}, queries=("a", "b", "c", "d"),
        query_languages=("en", "en", "en", "en"), budget_usd=0.0, max_documents=99,
    )
    return ResearchTask(**(base | over))


def _researcher(search, fetched="words"):
    return ApiResearcher(search=search, fetch=lambda url: fetched,
                         complete=lambda prompt: "", spend=STANDARD)


def test_a_run_under_its_ceiling_is_not_stopped():
    search = _Search()
    documents = _researcher(search).gather(_task(seconds=60.0))
    assert len(documents) == 4
    assert search.calls == 4


def test_the_ceiling_stops_a_run_that_is_going_nowhere():
    """The one query in flight finishes; the next is never issued.

    The clock starts on the first charge, so the first query is always sent —
    the check exists to stop the *next* call, not to predict this one. Four
    queries are configured and one is made.
    """
    search = _Search(delay=0.06)
    with pytest.raises(BudgetExceeded) as stopped:
        _researcher(search).gather(_task(seconds=0.05))
    assert "limit" in str(stopped.value)
    assert "s of its" in str(stopped.value)
    assert search.calls == 1, "a query after the deadline was still issued"
    assert search.calls < 4


def test_no_ceiling_means_no_clock():
    """`seconds=0.0` is the old behaviour, and the default for a caller that
    never sets one."""
    search = _Search(delay=0.02)
    assert len(_researcher(search).gather(_task(seconds=0.0))) == 4


def test_the_clock_belongs_to_the_run_not_to_the_researcher():
    """One researcher, two runs: the second gets its own clock."""
    search = _Search(delay=0.04)
    researcher = _researcher(search)
    with pytest.raises(BudgetExceeded):
        researcher.gather(_task(seconds=0.05))
    # A fresh `gather` resets `_started`, so a run after a slow one is not
    # instantly over.
    assert len(researcher.gather(_task(queries=("only",), query_languages=("en",),
                                       seconds=60.0))) == 1


def test_the_message_names_time_not_money():
    search = _Search(delay=0.06)
    with pytest.raises(BudgetExceeded) as stopped:
        _researcher(search).gather(_task(seconds=0.05))
    assert "$" not in str(stopped.value)
