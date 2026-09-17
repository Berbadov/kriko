"""Research and pack builds, started from a browser and survivable.

G6's delivery constraint is that nothing in the data path is terminal-only, and
that "with a visible result, error, and durable status" is the load-bearing
half: a job that fails silently, or that claims to be running after the process
died, would satisfy the endpoint and miss the point. So these tests pin the
unhappy paths — failure text, cancel, and restart — at least as hard as the
happy one.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.jobs import Cancelled, JobRunner
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
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def wait_for_done(conn, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = state.get_job(conn, job_id)
        if row and row["done"]:
            return row
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {state.get_job(conn, job_id)}")


def runner_with(settings, handler):
    return JobRunner(settings, {"probe": handler})


def test_a_finished_job_keeps_its_result_and_its_log(settings):
    def handler(_settings, params, progress):
        progress.log("started")
        progress.set(1.0, "7 claim(s) kept")
        return {"echo": params["value"]}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {"value": 7})
    conn = state.connect(settings.app_state_path)
    row = wait_for_done(conn, job_id)

    assert row["state"] == state.SUCCEEDED
    assert row["result"] == {"echo": 7}
    # A succeeded job reads 100%, whatever the handler last reported: a bar
    # stuck at 50% beside the word "done" is a bug report waiting to happen.
    assert row["progress"] == 1.0
    # And it keeps the handler's own last word rather than overwriting it with
    # "done". A word carrying no information is how the research job came to
    # look like a dead button: it succeeded, wrote a full brief, and reported
    # one syllable that named none of it.
    assert row["message"] == "7 claim(s) kept"
    assert row["log"] == "started\n"
    runner.shutdown(wait=True)


def test_a_failing_job_says_why_instead_of_vanishing(settings):
    def handler(_settings, _params, _progress):
        raise ValueError("no subject_id")

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    row = wait_for_done(conn, job_id)

    assert row["state"] == state.FAILED
    assert "no subject_id" in row["message"]
    # The traceback belongs in the row, not in whichever terminal started the
    # server — an operator reading the dashboard should not have to find it.
    assert "ValueError" in row["log"]
    runner.shutdown(wait=True)


def test_cancel_stops_a_running_job_at_its_next_checkpoint(settings):
    def handler(_settings, _params, progress):
        for _ in range(500):
            progress.check()
            time.sleep(0.01)
        return {"finished": True}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)

    deadline = time.time() + 5
    while time.time() < deadline:
        if (state.get_job(conn, job_id) or {})["state"] == state.RUNNING:
            break
        time.sleep(0.02)

    # `CANCELLING` while it tears down, `CANCELLED` once it has. The two used
    # to be one word plus a message, so a reader watching a run they had
    # stopped saw `cancelled` while it was still spending.
    assert runner.cancel(job_id) in {state.CANCELLING, state.CANCELLED}
    row = wait_for_done(conn, job_id)
    assert row["state"] == state.CANCELLED
    runner.shutdown(wait=True)


def test_a_queued_job_is_cancelled_outright(settings):
    """Nothing has started, so there is nothing to ask nicely."""

    def handler(_settings, _params, progress):
        time.sleep(0.4)
        return {}

    runner = runner_with(settings, handler)
    first = runner.submit("probe", {})
    second = runner.submit("probe", {})
    assert runner.cancel(second) == state.CANCELLED

    conn = state.connect(settings.app_state_path)
    assert state.get_job(conn, second)["state"] == state.CANCELLED
    wait_for_done(conn, first)
    # The worker must not run a row it was told to drop.
    assert state.get_job(conn, second)["result"] is None
    runner.shutdown(wait=True)


def test_a_job_the_process_died_under_becomes_interrupted(settings):
    """The whole reason state lives in a row rather than in the thread."""
    conn = state.connect(settings.app_state_path)
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)

    assert JobRunner(settings, {}).recover() == 1
    row = state.get_job(conn, job_id)
    assert row["state"] == state.INTERRUPTED
    assert row["done"] is True
    assert "stopped" in row["message"]


def test_cancelled_is_raised_as_cancelled_not_as_a_failure(settings):
    def handler(_settings, _params, _progress):
        raise Cancelled()

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    assert wait_for_done(conn, job_id)["state"] == state.CANCELLED
    runner.shutdown(wait=True)


def test_research_over_http_returns_an_id_and_then_a_status(client):
    started = client.post("/api/research", json={"subject_id": "nope"})
    assert started.status_code == 200
    job_id = started.json()["job_id"]

    # An unknown subject is a failed job, not a 500 on the POST: the request
    # only promises the job exists.
    for _ in range(400):
        row = client.get(f"/api/jobs/{job_id}").json()
        if row["done"]:
            break
        time.sleep(0.02)
    assert row["state"] == state.FAILED
    assert "nope" in row["message"] or "nope" in row["log"]

    listed = client.get("/api/jobs").json()["items"]
    assert [item["job_id"] for item in listed] == [job_id]


def test_an_unknown_job_is_a_404(client):
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.post("/api/jobs/missing/cancel").status_code == 404
    assert client.post("/api/jobs/missing/retry").status_code == 404


def test_a_failed_job_can_be_run_again_without_losing_why_it_failed(client):
    """Retry is a new row, not a reset.

    The failed attempt's log is the only record of *why* it failed, and reusing
    the row would delete the evidence at the exact moment someone is looking
    into it. The two are linked by `retry_of` instead.
    """
    first = client.post("/api/research", json={"subject_id": "nope"}).json()["job_id"]
    for _ in range(400):
        original = client.get(f"/api/jobs/{first}").json()
        if original["done"]:
            break
        time.sleep(0.02)
    assert original["state"] == state.FAILED

    again = client.post(f"/api/jobs/{first}/retry")
    assert again.status_code == 200
    second = again.json()["job_id"]
    assert second != first

    row = client.get(f"/api/jobs/{second}").json()
    assert row["kind"] == original["kind"]
    assert row["params"]["subject_id"] == "nope"
    assert row["params"]["retry_of"] == first
    # The evidence is still there.
    assert client.get(f"/api/jobs/{first}").json()["state"] == state.FAILED


def test_retrying_a_job_that_is_still_going_is_refused(settings):
    """"Retry" on a running job means the reader wanted to cancel it.

    Quietly starting a second copy of a research run is how you get two writers
    on one subject.
    """
    started = threading.Event()
    release = threading.Event()

    def slow(params, log, should_cancel):
        started.set()
        release.wait(5)
        return {}

    runner = JobRunner(settings, {"slow": slow})
    try:
        job_id = runner.submit("slow", {})
        assert started.wait(5)
        app = create_app(settings)
        app.state.jobs = runner
        # No lifespan on purpose: startup marks every running row `interrupted`,
        # which is right for a restarted process and would make this job look
        # finished to the very check under test.
        refused = TestClient(app).post(f"/api/jobs/{job_id}/retry")
        assert refused.status_code == 409
    finally:
        release.set()
        runner.shutdown(wait=True)


def test_the_agent_plane_still_produces_a_brief(client, settings):
    """The $0 plane gathers nothing by design; that is a result, not a failure."""
    from kriko.store.db import connect

    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'probe', 'product', 'Probe Thing')"
    )
    conn.commit()
    conn.close()

    # Named: `default_backend()` resolves an unnamed plane to the harness where
    # a coding-agent CLI is installed, and this test is about the other one.
    started = client.post(
        "/api/research", json={"subject_id": "s1", "backend": "agent"})
    job_id = started.json()["job_id"]
    for _ in range(500):
        row = client.get(f"/api/jobs/{job_id}").json()
        if row["done"]:
            break
        time.sleep(0.02)
    assert row["state"] == state.SUCCEEDED, row
    assert row["result"]["cost_basis"] == "subscription"
    assert row["result"]["brief"]
    assert row["result"]["accepted"] == []


def test_the_stream_ends_when_the_job_does(client):
    job_id = client.post("/api/research", json={"subject_id": "nope"}).json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "data:" in body
    assert state.FAILED in body


# ── cancelling must not cost the reader what they already paid for ──────
#
# "Cancel button buggy — kept going after clicking", and "cancel bins completed
# work". The second is the expensive one: `except Cancelled` wrote CANCELLED
# with no result, so sources fetched, pages read and findings extracted — all
# of it already paid for — died with the stack frame.

def test_a_cancelled_job_keeps_what_it_had_already_finished(settings):
    def handler(_settings, _params, progress):
        progress.partial({"documents": 3, "findings": 7,
                          "stopped_at": "extraction"})
        for _ in range(500):
            progress.check()
            time.sleep(0.01)
        return {"finished": True}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    deadline = time.time() + 5
    while time.time() < deadline:
        if (state.get_job(conn, job_id) or {})["state"] == state.RUNNING:
            break
        time.sleep(0.02)

    runner.cancel(job_id)
    row = wait_for_done(conn, job_id)
    assert row["state"] == state.CANCELLED
    assert row["result"]["documents"] == 3
    assert row["result"]["findings"] == 7
    assert row["result"]["partial"] is True, "kept work must be labelled incomplete"
    runner.shutdown(wait=True)


def test_a_cancelled_job_says_what_it_kept_rather_than_just_cancelled(settings):
    def handler(_settings, _params, progress):
        progress.partial({"documents": 2, "stopped_at": "extraction"})
        for _ in range(500):
            progress.check()
            time.sleep(0.01)
        return {}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    deadline = time.time() + 5
    while time.time() < deadline:
        if (state.get_job(conn, job_id) or {})["state"] == state.RUNNING:
            break
        time.sleep(0.02)
    runner.cancel(job_id)
    row = wait_for_done(conn, job_id)
    assert "extraction" in row["message"]
    assert "2 documents" in row["message"]
    runner.shutdown(wait=True)


def test_a_job_cancelled_before_it_finished_anything_says_so_plainly(settings):
    def handler(_settings, _params, progress):
        for _ in range(500):
            progress.check()
            time.sleep(0.01)
        return {}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    deadline = time.time() + 5
    while time.time() < deadline:
        if (state.get_job(conn, job_id) or {})["state"] == state.RUNNING:
            break
        time.sleep(0.02)
    runner.cancel(job_id)
    row = wait_for_done(conn, job_id)
    assert row["message"] == "stopped before anything was finished"
    assert not row["result"]
    runner.shutdown(wait=True)


def test_pressing_cancel_twice_does_not_queue_a_second_teardown(settings):
    """A button that looks like it did nothing gets pressed again."""
    def handler(_settings, _params, progress):
        for _ in range(500):
            progress.check()
            time.sleep(0.01)
        return {}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    deadline = time.time() + 5
    while time.time() < deadline:
        if (state.get_job(conn, job_id) or {})["state"] == state.RUNNING:
            break
        time.sleep(0.02)

    first = runner.cancel(job_id)
    second = runner.cancel(job_id)
    assert first == state.CANCELLING
    assert second in {state.CANCELLING, state.CANCELLED}
    row = wait_for_done(conn, job_id)
    assert row["state"] == state.CANCELLED
    runner.shutdown(wait=True)


def test_a_job_that_died_mid_teardown_is_not_left_spinning(settings):
    """`cancelling` is not terminal, so startup recovery has to cover it too."""
    conn = state.connect(settings.app_state_path)
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)
    state.request_cancel(conn, job_id)
    assert state.get_job(conn, job_id)["state"] == state.CANCELLING

    state.interrupt_running(conn)
    assert state.get_job(conn, job_id)["state"] == state.INTERRUPTED


# ── the one thing on the screen worth looking at ───────────────────────
#
# "If the agent is waiting on my answer, that must be unmissable." It is not
# waiting — the identification pass states its defaults and carries on — but a
# question rendered as another log line is a question nobody answers.

def test_a_run_with_questions_says_so_where_a_screen_will_see_it(settings):
    def handler(_settings, _params, progress):
        progress.partial({"questions": [
            {"id": "market", "ask": "Which market?", "default": "TR"},
            {"id": "year", "ask": "Which year?", "default": "2018"},
        ]})
        return {"questions": [
            {"id": "market", "ask": "Which market?", "default": "TR"},
            {"id": "year", "ask": "Which year?", "default": "2018"},
        ]}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    wait_for_done(conn, job_id)
    runner.shutdown(wait=True)

    with TestClient(create_app(settings)) as client:
        row = client.get(f"/api/jobs/{job_id}").json()
    assert row["attention"]["kind"] == "questions"
    assert row["attention"]["count"] == 2
    assert row["attention"]["say"]


def test_a_run_with_nothing_to_ask_raises_no_flag(settings):
    def handler(_settings, _params, _progress):
        return {"findings": 3}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    wait_for_done(conn, job_id)
    runner.shutdown(wait=True)

    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/jobs/{job_id}").json()["attention"] is None


def test_the_flag_survives_the_run_finishing(settings):
    """The answers make the *next* run exact, so they are worth offering
    beside "run it again" long after this one ended."""
    def handler(_settings, _params, _progress):
        return {"questions": [{"id": "a", "ask": "Which?", "default": "x"}]}

    runner = runner_with(settings, handler)
    job_id = runner.submit("probe", {})
    conn = state.connect(settings.app_state_path)
    row = wait_for_done(conn, job_id)
    runner.shutdown(wait=True)
    assert row["state"] == state.SUCCEEDED

    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/jobs/{job_id}").json()["attention"]["count"] == 1
