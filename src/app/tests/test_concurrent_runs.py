"""Agent runs at once, as many as Settings says, never two on one pack (#133).

The reader asked for "concurrent agent runs, with options in settings". The
runner was one worker on purpose: two jobs writing one pack directory is a bug
that must not be expressible. These pin both halves: the width is the reader's
choice and takes effect without a restart, and the per-pack line still holds,
in order, with a reason on the row of the one that waits.
"""

import threading
import time

import pytest

from app import prefs
from app.web import state
from app.web.jobs import EVERYTHING, JobRunner, claims
from app.web.settings import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
        packs_dir=tmp_path / "packs",
    )


@pytest.fixture
def conn(settings):
    conn = state.connect(settings.app_state_path)
    yield conn
    conn.close()


class Gate:
    """A handler that records when it is running and holds until released."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running: set[str] = set()
        self.peak = 0
        self.order: list[str] = []
        self.release = threading.Event()

    def __call__(self, _settings, params, _progress):
        name = params["name"]
        with self.lock:
            self.running.add(name)
            self.order.append(name)
            self.peak = max(self.peak, len(self.running))
        self.release.wait(10)
        with self.lock:
            self.running.discard(name)
        return {"name": name}


def wait_until(test, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if test():
            return
        time.sleep(0.02)
    raise AssertionError("condition never held")


def wait_all_done(conn, ids, timeout=10.0):
    wait_until(lambda: all(state.get_job(conn, i)["done"] for i in ids), timeout)


def runner(settings, gate):
    return JobRunner(settings, {"research": gate, "pack_author": gate, "odd": gate})


def test_one_is_the_default_and_runs_serially(settings, conn):
    gate = Gate()
    jobs = runner(settings, gate)
    ids = [jobs.submit("research", {"pack_id": f"p{i}", "name": f"r{i}"}) for i in range(3)]
    wait_until(lambda: len(gate.running) == 1)
    time.sleep(0.2)
    assert len(gate.running) == 1
    gate.release.set()
    wait_all_done(conn, ids)
    assert gate.peak == 1
    assert gate.order == ["r0", "r1", "r2"]
    jobs.shutdown()


def test_the_setting_runs_that_many_at_once(settings, conn):
    state.put_settings(conn, {prefs.RUN_CONCURRENCY: 3})
    gate = Gate()
    jobs = runner(settings, gate)
    ids = [jobs.submit("research", {"pack_id": f"p{i}", "name": f"r{i}"}) for i in range(4)]
    wait_until(lambda: len(gate.running) == 3)
    time.sleep(0.2)
    assert len(gate.running) == 3
    fourth = state.get_job(conn, ids[3])
    assert fourth["state"] == state.QUEUED
    assert "at once" in fourth["message"]
    gate.release.set()
    wait_all_done(conn, ids)
    assert gate.peak == 3
    jobs.shutdown()


def test_two_runs_on_one_pack_never_overlap_and_keep_their_order(settings, conn):
    state.put_settings(conn, {prefs.RUN_CONCURRENCY: 4})
    gate = Gate()
    jobs = runner(settings, gate)
    first = jobs.submit("research", {"pack_id": "same", "name": "a"})
    wait_until(lambda: "a" in gate.running)
    second = jobs.submit("research", {"pack_id": "same", "name": "b"})
    other = jobs.submit("research", {"pack_id": "elsewhere", "name": "c"})
    wait_until(lambda: "c" in gate.running)
    time.sleep(0.2)
    assert gate.running == {"a", "c"}
    waiting = state.get_job(conn, second)
    assert waiting["state"] == state.QUEUED
    assert "same pack" in waiting["message"]
    gate.release.set()
    wait_all_done(conn, [first, second, other])
    assert gate.order.index("a") < gate.order.index("b")
    jobs.shutdown()


def test_a_run_that_cannot_name_its_target_runs_alone(settings, conn):
    state.put_settings(conn, {prefs.RUN_CONCURRENCY: 4})
    gate = Gate()
    jobs = runner(settings, gate)
    first = jobs.submit("research", {"pack_id": "p", "name": "a"})
    wait_until(lambda: "a" in gate.running)
    alone = jobs.submit("odd", {"name": "odd"})
    # Later than the one that must run alone, so it may not slip past it.
    later = jobs.submit("research", {"pack_id": "q", "name": "late"})
    time.sleep(0.3)
    assert gate.running == {"a"}
    assert "alone" in state.get_job(conn, alone)["message"]
    gate.release.set()
    wait_all_done(conn, [first, alone, later])
    assert gate.order == ["a", "odd", "late"]
    jobs.shutdown()


def test_raising_the_setting_takes_effect_without_a_restart(settings, conn):
    gate = Gate()
    jobs = runner(settings, gate)
    ids = [jobs.submit("research", {"pack_id": f"p{i}", "name": f"r{i}"}) for i in range(2)]
    wait_until(lambda: len(gate.running) == 1)
    state.put_settings(conn, {prefs.RUN_CONCURRENCY: 2})
    # The next pump picks it up: a third submit is one.
    ids.append(jobs.submit("research", {"pack_id": "p9", "name": "r9"}))
    wait_until(lambda: len(gate.running) == 2)
    gate.release.set()
    wait_all_done(conn, ids)
    jobs.shutdown()


def test_a_cancelled_waiting_run_gives_its_place_back(settings, conn):
    gate = Gate()
    jobs = runner(settings, gate)
    first = jobs.submit("research", {"pack_id": "p", "name": "a"})
    wait_until(lambda: "a" in gate.running)
    dropped = jobs.submit("research", {"pack_id": "p", "name": "dropped"})
    jobs.cancel(dropped)
    gate.release.set()
    wait_all_done(conn, [first, dropped])
    assert state.get_job(conn, dropped)["state"] == state.CANCELLED
    assert "dropped" not in gate.order
    jobs.shutdown()


def test_a_subject_nobody_installed_claims_everything(settings):
    jobs = JobRunner(settings, {})
    assert claims("research", jobs._with_pack({"subject_id": "nobody"})) == {EVERYTHING}
    jobs.shutdown()


@pytest.mark.parametrize("stored, expected", [
    (None, 1), (1, 1), (3, 3), ("2", 2), (99, prefs.MAX_RUN_CONCURRENCY),
    (0, 1), (-2, 1), ("many", 1),
])
def test_the_setting_is_clamped_and_never_an_error(conn, stored, expected):
    if stored is not None:
        state.put_settings(conn, {prefs.RUN_CONCURRENCY: stored})
    assert prefs.run_concurrency(conn) == expected


def test_claims_name_the_pack_from_the_jobs_own_params():
    assert claims("research", {"pack_id": "owner"}) == {"pack:owner"}
    assert claims("verify", {"pack_id": "x"}) == {"pack:x"}
    assert claims("pack_build", {"root": "C:\\packs\\x\\"}) == {"pack:x"}
    assert claims("pack_update", {"installed_only": True}) == {EVERYTHING}
    assert claims("pack_author", {}) == claims("pack_amend", {"slug": "s"})
    assert claims("model_pull", {"model": "m"}) == {"model:m"}
    assert claims("never_heard_of_it", {"pack_id": "x"}) == {EVERYTHING}
