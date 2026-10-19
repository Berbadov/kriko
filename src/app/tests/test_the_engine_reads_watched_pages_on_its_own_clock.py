"""A watch is read when nobody is looking: the engine's own clock submits the sweep."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from app import pricescheduler, pricewatch
from app.web import state


@pytest.fixture
def path(tmp_path):
    return tmp_path / "app.sqlite"


def watch_one(path, *, when=None):
    conn = state.connect(path)
    pricewatch.watch(conn, "https://shop.test/p/kettle", "Kettle", target=30, now=when)
    conn.close()


def test_nothing_watched_submits_nothing(path):
    submitted = []
    sweeper = pricescheduler.Sweeper(path, lambda: submitted.append(1) or "j1")
    assert sweeper.tick() == "" and submitted == []


def test_a_watched_page_that_was_never_read_is_swept_once_until_that_job_ends(path):
    watch_one(path)
    submitted = []
    sweeper = pricescheduler.Sweeper(path, lambda: submitted.append(1) or "j1")
    conn = state.connect(path)
    job_id = state.create_job(conn, "price_sweep", {})
    conn.close()
    sweeper.submit = lambda: submitted.append(1) or job_id
    assert sweeper.tick() == job_id
    # The sweep is still running: a second tick does not stack another.
    assert sweeper.tick() == "" and len(submitted) == 1
    conn = state.connect(path)
    state.finish_job(conn, job_id, state.SUCCEEDED, result={})
    conn.close()
    # It finished and the page is still unread, so the next tick asks again.
    assert sweeper.tick() == job_id and len(submitted) == 2


def test_a_page_read_a_moment_ago_is_not_due(path):
    watch_one(path)
    conn = state.connect(path)
    pricewatch.record(conn, "https://shop.test/p/kettle", "Kettle", {"price": 40, "currency": "EUR"},
                      now=datetime.now(UTC) - timedelta(minutes=5))
    conn.close()
    submitted = []
    assert pricescheduler.Sweeper(path, lambda: submitted.append(1) or "j").tick() == ""
    assert submitted == []


def test_the_clock_ticks_on_its_own_thread_and_stops_when_told(path):
    watch_one(path)
    seen = []
    sweeper = pricescheduler.Sweeper(path, lambda: seen.append(1) or "")
    stop = pricescheduler.start(sweeper, every=0.02)
    deadline = time.time() + 3
    while not seen and time.time() < deadline:
        time.sleep(0.02)
    stop()
    assert seen, "the clock never ticked"
    count = len(seen)
    time.sleep(0.15)
    assert len(seen) <= count + 1


def test_a_tick_that_fails_does_not_end_the_clock(path):
    calls = []

    class Broken(pricescheduler.Sweeper):
        def tick(self):
            calls.append(1)
            raise RuntimeError("boom")

    stop = pricescheduler.start(Broken(path, lambda: ""), every=0.02)
    deadline = time.time() + 3
    while len(calls) < 3 and time.time() < deadline:
        time.sleep(0.02)
    stop()
    assert len(calls) >= 3


def test_the_interval_is_half_an_hour_and_can_be_set(monkeypatch):
    monkeypatch.delenv("KRIKO_PRICE_SWEEP_MINUTES", raising=False)
    assert pricescheduler.interval_seconds() == 1800
    monkeypatch.setenv("KRIKO_PRICE_SWEEP_MINUTES", "5")
    assert pricescheduler.interval_seconds() == 300
    monkeypatch.setenv("KRIKO_PRICE_SWEEP_MINUTES", "nonsense")
    assert pricescheduler.interval_seconds() == 1800
