"""The politeness scheduler's wait is a wait, never a negative number.

`_soonest_ready` answers "how long until any source may be used again", and
`acquire` hands that to its caller as a sleep. It built its first list from
`now < hot_until or hot_until <= now` — true for every source, so the filter did
nothing — and when every source was in cooldown it measured from `next_ready`
alone, ignoring the cooldown that was the actual reason to wait. The caller was
then handed a negative duration, which is no sleep at all.
"""

from kriko.research.politeness import PolitenessScheduler


def _scheduler(**intervals):
    return PolitenessScheduler(intervals, max_in_flight=4, cooldown=30.0)


def test_an_idle_scheduler_asks_for_no_wait():
    assert _scheduler(one=1.0)._soonest_ready() == 0.0


def test_a_rate_interval_is_the_wait_when_nothing_is_hot():
    scheduler = _scheduler(one=0.2)
    scheduler.acquire()
    assert 0.0 < scheduler._soonest_ready() <= 0.25


def test_a_cooldown_is_what_the_wait_is_measured_from():
    """A source hot for 30 s with no rate interval must report about that."""
    scheduler = _scheduler(one=0.0)
    scheduler.acquire()
    scheduler.report("one", blocked=True)
    assert 0.0 < scheduler._soonest_ready() <= 31.0


def test_a_wait_is_never_negative():
    """The caller sleeps this value; a negative one is a silent no-op."""
    scheduler = _scheduler(one=0.0)
    scheduler.acquire()
    scheduler.report("one", blocked=True)
    assert scheduler._soonest_ready() >= 0.0


def test_the_soonest_source_decides_not_the_slowest():
    scheduler = _scheduler(one=0.0, two=0.0)
    name, _delay = scheduler.acquire()
    scheduler.report(name, blocked=True)
    # One source is in cooldown; the other was never used, so nothing is due.
    assert scheduler._soonest_ready() == 0.0


def test_every_source_hot_still_reports_a_non_negative_wait():
    """The case the old expression got wrong: nothing available at all."""
    scheduler = _scheduler(one=0.0, two=0.0)
    for _ in range(2):
        name, _delay = scheduler.acquire()
        scheduler.report(name, blocked=True)
    assert scheduler._soonest_ready() >= 0.0
