"""Saying something to a run that is already going.

The gap B120 named and left open: the prompt went in once and the transcript
came out, so a run that stopped to ask a question could be watched and stopped
and nothing else. That is a window, not a conversation.

The reply path is deliberately the same shape as cancel — a row the handler
reads between steps — because the handler is a thread in this process and the
answer arrives on another. So these tests pin the same things cancel's do: that
a line reaches a running handler, that it reaches it *once*, and that answering
something already over is told it did not land rather than being refused.
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.jobs import JobRunner
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
    connection = state.connect(settings.app_state_path)
    yield connection
    connection.close()


# ── the row underneath ──────────────────────────────────────────────────

def test_a_line_reaches_a_running_job(conn):
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)

    assert state.say_to_job(conn, job_id, "the 2014 one") is True
    assert state.take_job_messages(conn, job_id) == ["the 2014 one"]


def test_a_line_is_handed_over_exactly_once(conn):
    # Handing it twice means a harness types it twice, which means paying for
    # it twice — the reason the read and the mark share a transaction.
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)
    state.say_to_job(conn, job_id, "yes")

    assert state.take_job_messages(conn, job_id) == ["yes"]
    assert state.take_job_messages(conn, job_id) == []


def test_lines_arrive_in_the_order_they_were_said(conn):
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)
    state.say_to_job(conn, job_id, "first")
    state.say_to_job(conn, job_id, "second")

    assert state.take_job_messages(conn, job_id) == ["first", "second"]


def test_a_job_that_has_ended_cannot_be_answered(conn):
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)
    state.finish_job(conn, job_id, state.SUCCEEDED, result={})

    assert state.say_to_job(conn, job_id, "too late") is False
    assert state.take_job_messages(conn, job_id) == []


def test_a_job_still_queued_can_be_answered(conn):
    # It has not started reading yet, but it will, and the line keeps.
    job_id = state.create_job(conn, "probe", {})

    assert state.say_to_job(conn, job_id, "early") is True


def test_blank_is_not_a_reply(conn):
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)

    assert state.say_to_job(conn, job_id, "   ") is False
    assert state.take_job_messages(conn, job_id) == []


def test_replies_are_not_crossed_between_jobs(conn):
    one = state.create_job(conn, "probe", {})
    two = state.create_job(conn, "probe", {})
    state.start_job(conn, one)
    state.start_job(conn, two)
    state.say_to_job(conn, one, "for one")

    assert state.take_job_messages(conn, two) == []
    assert state.take_job_messages(conn, one) == ["for one"]


# ── the handler's side ──────────────────────────────────────────────────

def test_a_running_handler_reads_what_was_said(settings, conn):
    """End to end through the runner, because that is where it has to work.

    The handler blocks until something is said to it, exactly as a harness
    waiting on its own question would.
    """
    heard: list[str] = []

    def handler(_settings, _params, progress):
        deadline = time.time() + 10.0
        while time.time() < deadline:
            lines = progress.replies()
            if lines:
                heard.extend(lines)
                return {"heard": lines}
            time.sleep(0.02)
        raise AssertionError("nothing was ever said to the run")

    runner = JobRunner(settings, {"probe": handler})
    job_id = runner.submit("probe", {})
    row = None
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if state.say_to_job(conn, job_id, "the 1.6 TDI"):
                break
            time.sleep(0.02)
        else:  # pragma: no cover - only on a runner that never starts
            raise AssertionError("the job never reached a state that could hear")

        deadline = time.time() + 10.0
        while time.time() < deadline:
            row = state.get_job(conn, job_id)
            if row and row["done"]:
                break
            time.sleep(0.02)
    finally:
        runner.shutdown()

    assert heard == ["the 1.6 TDI"]
    assert row is not None and row["result"] == {"heard": ["the 1.6 TDI"]}


# ── the door ────────────────────────────────────────────────────────────

def test_the_endpoint_reports_whether_it_landed(settings):
    with TestClient(create_app(settings)) as client:
        # Created after startup, on purpose: startup marks every unfinished row
        # `interrupted`, since nothing can still be executing one. A row made
        # before the client exists is therefore already over by the time this
        # posts to it, and would be testing the opposite of what it says.
        conn = state.connect(settings.app_state_path)
        job_id = state.create_job(conn, "probe", {})
        state.start_job(conn, job_id)
        conn.close()

        answer = client.post(f"/api/jobs/{job_id}/say", json={"text": "hello"})
        assert answer.status_code == 200
        assert answer.json() == {"job_id": job_id, "delivered": True}


def test_answering_a_finished_run_is_not_an_error(settings):
    """`delivered: false`, not a 409.

    The reader was answering a question that stopped mattering while they
    typed. That is not a mistake to refuse them for — but they must not be
    told it landed.
    """
    conn = state.connect(settings.app_state_path)
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)
    state.finish_job(conn, job_id, state.SUCCEEDED, result={})
    conn.close()

    with TestClient(create_app(settings)) as client:
        answer = client.post(f"/api/jobs/{job_id}/say", json={"text": "hello"})
        assert answer.status_code == 200
        assert answer.json()["delivered"] is False


def test_answering_a_job_that_does_not_exist_is_a_404(settings):
    with TestClient(create_app(settings)) as client:
        answer = client.post("/api/jobs/nope/say", json={"text": "hello"})
        assert answer.status_code == 404
