"""The log has to exist, and an unwritable path has to be visible.

These are the tests that were missing when the whole class of bug went
unnoticed for two months: every analysis append on the development machine
failed into a root-owned `logs/`, reported it through a `log.warning` with no
configured handler, and every gate in the repository stayed green.

So the assertions are deliberately about *reporting*, not about happy paths.
A test that only proves the log gets written when the directory is writable
would have passed the whole time.
"""

import logging
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import logs
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture(autouse=True)
def clean_handlers():
    logs.reset_for_tests()
    yield
    logs.reset_for_tests()


def _skip_unless_write_can_be_denied(directory) -> None:
    """Skip where the OS will not let a chmod take write permission away.

    Three tests below need exactly one condition: a directory this process
    cannot write into. Two platforms decline to express it — root, for whom
    the mode bits are advisory, and Windows, where `chmod` on a directory
    changes nothing and `os.geteuid` is not even defined. The guard here
    named only the first, so on the Windows host that runs the gate all three
    died with an `AttributeError` before reaching an assertion, and the reason
    the suite was red there had nothing to do with logging.

    Probed rather than named after a platform: what these tests need is that
    the denial *took*, and trying to write answers that directly — on this OS,
    as this user, under whatever the filesystem actually enforces.
    """
    probe = Path(directory) / ".probe-write-denied"
    try:
        probe.write_text("x", encoding="utf-8")
    except OSError:
        return
    probe.unlink()
    pytest.skip("this OS does not let a chmod deny writing to a directory")


def test_probe_names_the_reason_not_just_a_no(tmp_path):
    """"Cannot write" is not actionable; a path and an errno are."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        _skip_unless_write_can_be_denied(blocked)
        why = logs.probe(blocked / "app.log")
    finally:
        blocked.chmod(stat.S_IRWXU)
    assert why is not None
    assert "app.log" in why or "Permission" in why


def test_probe_passes_on_a_directory_that_does_not_exist_yet(tmp_path):
    """A first run has no ~/.kriko/logs. That is not a failure."""
    assert logs.probe(tmp_path / "deep" / "nested" / "app.log") is None


def test_resolve_falls_back_rather_than_refusing(tmp_path):
    """Fail open — but hand back the reason, which is the part that was missing."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    good = tmp_path / "good" / "analyses.jsonl"
    try:
        _skip_unless_write_can_be_denied(blocked)
        path, why = logs.resolve_writable(blocked / "analyses.jsonl", good)
    finally:
        blocked.chmod(stat.S_IRWXU)
    assert path == good
    assert why is not None


def test_configure_writes_a_file_and_reports_it(tmp_path):
    path = tmp_path / "logs" / "app.log"
    assert logs.configure(path) == path
    logging.getLogger("kriko.test").error("a thing went wrong")
    assert "a thing went wrong" in path.read_text(encoding="utf-8")
    assert logs.active_path() == path
    assert logs.failure_reason() is None


def test_configure_twice_does_not_double_every_line(tmp_path):
    path = tmp_path / "app.log"
    logs.configure(path)
    logs.configure(path)
    logging.getLogger("kriko.test").error("once")
    assert path.read_text(encoding="utf-8").count("once") == 1


def test_health_names_the_log_file(tmp_path):
    logs.configure(tmp_path / "app.log")
    client = TestClient(create_app(Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "a.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    )))
    body = client.get("/api/health").json()
    assert body["log_file"] == str(tmp_path / "app.log")
    assert body["log_problem"] is None
    assert body["analysis_log_problem"] is None


def test_health_reports_an_unwritable_analysis_log(tmp_path):
    """The regression under test: a swallowed write and a green suite."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        _skip_unless_write_can_be_denied(blocked)
        client = TestClient(create_app(Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "a.sqlite",
            analysis_log_path=blocked / "analyses.jsonl",
        )))
        body = client.get("/api/health").json()
    finally:
        blocked.chmod(stat.S_IRWXU)
    assert body["analysis_log_problem"] is not None
    # And it moved somewhere it can actually write, rather than failing every
    # append for the life of the install.
    assert body["analysis_log"] != str(blocked / "analyses.jsonl")


def test_an_unhandled_error_reaches_the_log_file(tmp_path):
    """`explain_the_failure` used to print to a stderr nobody kept."""
    path = tmp_path / "app.log"
    logs.configure(path)
    app = create_app(Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "a.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    ))

    @app.get("/api/_boom")
    def boom():
        raise RuntimeError("deliberate")

    client = TestClient(app, raise_server_exceptions=False)
    client.get("/api/_boom")
    written = path.read_text(encoding="utf-8")
    assert "deliberate" in written
    assert "/api/_boom" in written


def test_a_rollover_another_process_blocks_loses_no_line(tmp_path):
    """Windows will not rename a file someone else holds open, and the stock
    handler then dropped every record — the installed app wrote nothing into
    a log sitting just over its rotation size. The open handle here stands in
    for the other process; on a system that allows the rename it rotates."""
    path = tmp_path / "app.log"
    path.write_text("x" * (logs.MAX_BYTES + 10), encoding="utf-8")
    with path.open("a", encoding="utf-8"):
        assert logs.configure(path) == path
        logging.getLogger("kriko.test").error("the line that matters")
        logging.getLogger("kriko.test").error("and the one after it")
    for handler in logging.getLogger().handlers:
        handler.flush()
    written = "".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in tmp_path.glob("app.log*")
    )
    assert "the line that matters" in written
    assert "and the one after it" in written
