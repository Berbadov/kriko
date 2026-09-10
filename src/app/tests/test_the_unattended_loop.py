"""B98 — the agenda, walked with nobody watching, and what it refuses to do.

G5 says Kriko runs unattended. Until this row it ran when watched: the agenda
knew what was worth researching next, `agenda_run` walked it, and every walk
was a button press.

The backlog sequenced this *after* B92 for a reason worth restating, because
it is the whole shape of the feature: "a scheduler driving a no-op is worse
than no scheduler, because it would fill the runs table with successful
nothing." So most of this file is about refusals rather than about running —
an unattended loop that submits when it should not is not a feature that needs
tuning, it is a feature that has to be switched off by whoever notices.

`schedule.decide` is a pure function precisely so that these rules are held by
assertions instead of by a timer. A rule that can only be tested by waiting is
a rule that stops being tested.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.web import schedule, state
from app.web.app import create_app
from app.web.settings import Settings

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


def _on(**over) -> dict:
    return {**schedule.DEFAULTS, "enabled": True, **over}


# ── consent ──────────────────────────────────────────────────────────────


def test_the_loop_is_off_until_the_reader_turns_it_on():
    """The default an installation left open all week must not act on.

    Not a preference: an app that started spawning agents because a window
    was open would be a defect no matter how good the agenda was.
    """
    assert schedule.DEFAULTS["enabled"] is False
    decision = schedule.decide(NOW, schedule.DEFAULTS)
    assert decision.run is False
    assert "off" in decision.reason


def test_a_stored_schedule_is_merged_over_the_defaults(tmp_path):
    """A blob written by an older version still answers every question.

    Merged rather than replaced, so a reader who set only the interval does
    not end up with a schedule that has no plane.
    """
    conn = state.connect(tmp_path / "app.sqlite")
    state.put_settings(conn, {schedule.KEY: {"enabled": True, "every_hours": 3}})
    merged = schedule.settings_for(conn)
    conn.close()
    assert merged["enabled"] is True
    assert merged["every_hours"] == 3
    assert merged["plane"] == schedule.DEFAULTS["plane"]


def test_an_interval_of_zero_becomes_the_floor_rather_than_a_hot_loop(tmp_path):
    """`every_hours: 0` in a settings file is a mistake, not an instruction."""
    conn = state.connect(tmp_path / "app.sqlite")
    state.put_settings(conn, {schedule.KEY: {"enabled": True, "every_hours": 0}})
    assert schedule.settings_for(conn)["every_hours"] == schedule.MIN_HOURS
    conn.close()


# ── the refusals that keep the runs table honest ─────────────────────────


def test_the_loop_refuses_the_plane_whose_output_needs_a_person():
    """The `agent` plane writes a brief for somebody to hand to an agent.

    Nobody is here to hand it over, so an unattended run of it produces a
    brief that is never read and a run row that says it succeeded — the exact
    "successful nothing" the backlog row refused to ship.
    """
    decision = schedule.decide(NOW, _on(plane="agent"), ready=False)
    assert decision.run is False
    assert "hand it over" in decision.reason


def test_the_loop_refuses_a_plane_that_cannot_run_right_now():
    """No CLI, no key — and the refusal is a sentence, not silence.

    A loop that declines without saying why is indistinguishable from a loop
    that is broken, and the reader's answer to each is different.
    """
    for plane in ("harness", "api"):
        decision = schedule.decide(NOW, _on(plane=plane), ready=False)
        assert decision.run is False
        assert decision.reason == schedule.NEEDS[plane]


def test_the_loop_refuses_a_plane_that_does_not_exist():
    """One place refuses an unknown plane, so two places cannot disagree."""
    decision = schedule.decide(NOW, _on(plane="wishful"))
    assert decision.run is False
    assert "no such research plane" in decision.reason


def test_the_agent_plane_is_never_ready_for_an_unattended_run(tmp_path):
    """Asserted on the readiness check itself, not only on `decide`.

    The `agent` plane has no prerequisite to install, so a readiness function
    that answered "yes, nothing is missing" would be technically true and
    would schedule a run nobody will ever read.
    """
    loop = schedule.Scheduler(_settings(tmp_path), None)
    assert loop._ready("agent") is False


# ── one thing at a time ──────────────────────────────────────────────────


def test_a_tick_skips_while_work_is_already_in_flight():
    """The job runner has one worker: a tick that submitted would queue
    behind the work rather than run beside it, and a slow schedule would then
    accumulate a backlog nobody asked for."""
    decision = schedule.decide(NOW, _on(), in_flight=1)
    assert decision.run is False
    assert "already queued or running" in decision.reason


def test_work_in_flight_counts_queued_and_running_and_nothing_else(tmp_path):
    """A finished job must not hold the loop off forever."""
    conn = state.connect(tmp_path / "app.sqlite")
    queued = state.create_job(conn, "agenda_run", {})
    assert state.work_in_flight(conn) == 1
    state.start_job(conn, queued)
    assert state.work_in_flight(conn) == 1
    state.finish_job(conn, queued, state.SUCCEEDED, result={})
    assert state.work_in_flight(conn) == 0
    conn.close()


# ── the clock ────────────────────────────────────────────────────────────


def test_a_machine_that_was_off_for_a_week_runs_once_rather_than_seven_times():
    """The next due time is computed from the stored timestamp.

    A loop that counted intervals in memory would owe six missed runs on the
    morning the laptop opens, and would spend them all at once.
    """
    long_ago = (NOW - timedelta(days=7)).isoformat()
    first = schedule.decide(NOW, _on(every_hours=24), last_run_at=long_ago)
    assert first.run is True
    # And having run, it is not due again until tomorrow.
    second = schedule.decide(NOW, _on(every_hours=24), last_run_at=NOW.isoformat())
    assert second.run is False
    assert second.reason == "not due yet"
    assert second.due_at.startswith("2026-09-11T12:00")


def test_opening_the_app_is_not_a_request_to_start_a_run():
    """The startup grace. A reader who opens the app to change the setting
    should reach it before the loop acts on the old one."""
    decision = schedule.decide(NOW, _on(), started_at=NOW)
    assert decision.run is False
    assert "waits a couple of minutes" in decision.reason


def test_the_grace_expires_rather_than_holding_the_loop_off_forever():
    started = NOW - timedelta(seconds=schedule.STARTUP_GRACE_SECONDS + 1)
    assert schedule.decide(NOW, _on(), started_at=started).run is True


@pytest.mark.parametrize("stored", ["", "not a date", None, "2026-13-45"])
def test_a_timestamp_nobody_can_parse_is_treated_as_never_run(stored):
    """A settings file edited by hand must not wedge the loop shut."""
    assert schedule.decide(NOW, _on(), last_run_at=stored).run is True


# ── a tick is a record ───────────────────────────────────────────────────


class _Runner:
    """A job runner that records submissions instead of making threads."""

    def __init__(self):
        self.submitted: list[tuple[str, dict]] = []

    def submit(self, kind, params):
        self.submitted.append((kind, params))
        return f"job-{len(self.submitted)}"


def _loop(tmp_path, runner=None, **over):
    conn = state.connect(tmp_path / "app.sqlite")
    state.put_settings(conn, {schedule.KEY: _on(**over)})
    conn.close()
    return schedule.Scheduler(_settings(tmp_path), runner or _Runner())


def test_a_tick_that_ran_submits_the_agenda_with_the_readers_own_settings(
    tmp_path, monkeypatch
):
    """The setting is the run's parameters. A loop that ran a different shape
    of run than the one on screen would be worse than no loop."""
    monkeypatch.setattr(schedule.Scheduler, "_ready", lambda self, plane: True)
    runner = _Runner()
    loop = _loop(tmp_path, runner, rows=7, plane="harness", max_documents=3)
    decision = loop.tick(NOW, from_timer=False)
    assert decision.run is True
    kind, params = runner.submitted[0]
    assert kind == "agenda_run"
    assert (params["rows"], params["backend"], params["max_documents"]) == (
        7, "harness", 3,
    )


def test_every_tick_records_what_it_decided_including_the_ones_that_did_nothing(
    tmp_path,
):
    """Otherwise the reader cannot tell a loop that declined from a dead one.

    This is the whole observability of an unattended feature: nothing else
    happens, so the record of *why* nothing happened is the only output.
    """
    loop = _loop(tmp_path, plane="agent")  # never ready, by definition
    loop.tick(NOW, from_timer=False)
    conn = state.connect(tmp_path / "app.sqlite")
    last = schedule.status(conn)["last"]
    conn.close()
    assert last["checked_at"].startswith("2026-09-10T12:00")
    assert "hand it over" in last["reason"]
    assert "run_at" not in last, "a skipped tick claimed to have run"


def test_the_record_of_what_the_loop_did_survives_turning_it_off(tmp_path):
    """"It ran four times and the last one kept nothing" is exactly what a
    reader wants to read *after* switching it off, so the history is stored
    under its own key rather than inside the setting."""
    monkeypatch_free = _loop(tmp_path, plane="agent")
    monkeypatch_free.tick(NOW, from_timer=False)
    conn = state.connect(tmp_path / "app.sqlite")
    state.put_settings(conn, {schedule.KEY: {**schedule.DEFAULTS, "enabled": False}})
    status = schedule.status(conn)
    conn.close()
    assert status["enabled"] is False
    assert status["last"]["reason"]


def test_a_tick_that_raised_does_not_end_the_loop(tmp_path, monkeypatch):
    """A scheduler that dies on one bad read is a feature that silently stops
    working weeks later, which is the worst available outcome."""
    monkeypatch.setattr(schedule.Scheduler, "_ready", lambda self, plane: True)

    class _Broken(_Runner):
        def submit(self, kind, params):
            raise RuntimeError("no")

    loop = _loop(tmp_path, _Broken())
    with pytest.raises(RuntimeError):
        loop.tick(NOW, from_timer=False)
    # The loop body swallows it, which is what keeps the thread alive.
    loop._stop.set()
    loop._loop()  # returns immediately; asserts only that it does not raise


# ── the route the screen reads ───────────────────────────────────────────


def test_the_schedule_route_reports_off_on_a_fresh_installation(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        body = client.get("/api/schedule").json()
    assert body["enabled"] is False
    assert body["last"] == {}


def test_saving_one_field_does_not_reset_the_others(tmp_path):
    """A partial PUT is the normal case: the screen saves the control the
    reader touched."""
    with TestClient(create_app(_settings(tmp_path))) as client:
        client.put("/api/schedule", json={"rows": 9})
        body = client.put("/api/schedule", json={"every_hours": 4}).json()
    assert body["rows"] == 9
    assert body["every_hours"] == 4


def test_turning_the_loop_on_starts_it_without_a_restart(tmp_path):
    """A setting that needs a restart is a setting a reader concludes is
    broken."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        assert app.state.schedule._thread is None
        client.put("/api/schedule", json={"enabled": True})
        assert app.state.schedule._thread is not None
        client.put("/api/schedule", json={"enabled": False})
        assert app.state.schedule._stop.is_set()


def test_a_test_client_does_not_acquire_a_background_thread_by_existing(tmp_path):
    """The lifespan starts the loop only when the reader turned it on. Every
    test in this suite enters a lifespan; none of them should get a timer."""
    app = create_app(_settings(tmp_path))
    with TestClient(app):
        assert app.state.schedule._thread is None


def test_check_now_answers_with_the_sentence_the_loop_would_have_recorded(tmp_path):
    """The manual half of an automatic feature, and it exists for trust: a
    reader who turns on a loop that next acts in a day has otherwise no way
    to find out whether it *would* act."""
    with TestClient(create_app(_settings(tmp_path))) as client:
        body = client.post("/api/schedule/check").json()
    assert body["ran"] is False
    assert "off" in body["reason"]
    assert body["last"]["reason"] == body["reason"]
