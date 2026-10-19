"""`jobs` is the one table a panel open writes to, and it has to have a bound.

Every analysis, quick look and question is a job row, and nothing ever deleted
one: the reader's `app.sqlite` grew for the life of the installation while
`/api/jobs` paged 200 rows of it. The log column is capped now
(`JOB_LOG_CHARS`), and the rows are capped here — in `finish_job`, because that
is the only moment a job becomes history.

The subtlety the tests pin is the one that would make this dangerous: a row that
is still **queued, running or cancelling** is work, not history, however old it
looks. A prune that took those would delete a job the runner is about to finish,
and the reader's Queue would lose a row that is still running.
"""

import pytest

from app.web import state


@pytest.fixture
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


def _job(conn, job_id: str, job_state: str, at: str = "2026-01-01T00:00:00") -> None:
    conn.execute(
        "INSERT INTO jobs (job_id, kind, state, params_json, created_at,"
        " finished_at, log) VALUES (?,?,?,?,?,?,'')",
        (job_id, "quick_look", job_state, "{}", at, at),
    )
    conn.commit()


def test_finished_jobs_are_kept_to_the_bound(conn, monkeypatch):
    monkeypatch.setattr(state, "JOBS_KEPT", 5)
    for index in range(5):
        _job(conn, f"j-{index:02d}", state.SUCCEEDED, f"2026-01-01T00:00:{index:02d}")
    # The sixth finishing job is what pushes the table past the bound.
    _job(conn, "j-99", state.RUNNING, "2026-01-01T00:01:00")
    state.finish_job(conn, "j-99", state.SUCCEEDED)

    kept = [row[0] for row in conn.execute("SELECT job_id FROM jobs ORDER BY rowid")]
    assert len(kept) == 5
    assert "j-00" not in kept, "the oldest finished job is the one to drop"
    assert "j-99" in kept


def test_a_running_job_is_never_pruned(conn, monkeypatch):
    """It is work, not history — however old its row is."""
    monkeypatch.setattr(state, "JOBS_KEPT", 1)
    _job(conn, "j-old", state.RUNNING, "2026-01-01T00:00:00")
    _job(conn, "j-01", state.SUCCEEDED, "2026-01-01T00:00:01")
    _job(conn, "j-02", state.SUCCEEDED, "2026-01-01T00:00:02")
    state.finish_job(conn, "j-02", state.SUCCEEDED)

    kept = {row[0] for row in conn.execute("SELECT job_id FROM jobs")}
    assert "j-old" in kept, "a running job was deleted"
    assert "j-02" in kept, "the newest finished job must survive the bound"


def test_a_running_job_does_not_use_up_the_finished_budget(conn, monkeypatch):
    """Three live rows must not evict the whole of history."""
    monkeypatch.setattr(state, "JOBS_KEPT", 2)
    for index in range(3):
        _job(conn, f"live-{index}", state.RUNNING, f"2026-01-01T00:00:0{index}")
    _job(conn, "done-1", state.SUCCEEDED, "2026-01-01T00:01:00")
    _job(conn, "done-2", state.SUCCEEDED, "2026-01-01T00:01:01")
    state.finish_job(conn, "done-2", state.SUCCEEDED)

    kept = {row[0] for row in conn.execute("SELECT job_id FROM jobs")}
    assert {"done-1", "done-2"} <= kept
    assert {"live-0", "live-1", "live-2"} <= kept


def test_a_cancelling_job_is_never_pruned(conn, monkeypatch):
    monkeypatch.setattr(state, "JOBS_KEPT", 1)
    _job(conn, "j-stop", state.CANCELLING, "2026-01-01T00:00:00")
    _job(conn, "j-01", state.SUCCEEDED, "2026-01-01T00:00:01")
    _job(conn, "j-02", state.SUCCEEDED, "2026-01-01T00:00:02")
    state.finish_job(conn, "j-02", state.SUCCEEDED)
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE job_id = 'j-stop'").fetchone()[0] == 1
