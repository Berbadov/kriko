"""The terminal, now that it is ordinary HTTP.

These replace `test_terminal_ws.py`, which is gone with the socket. Each test
there guarded a path out of the WebSocket handler that could reach the reader
as a bare "[disconnected]"; the equivalent property here is stronger and
cheaper to hold, because the failure is a *field on the session* rather than a
frame someone had to be connected to receive.
"""

import json
import time

import pytest

from app.providers import termpty
from app.web.app import create_app
from app.web.origins import terminal_origin_is_allowed
from app.web.settings import Settings


def _client(tmp_path):
    from fastapi.testclient import TestClient

    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


@pytest.fixture(autouse=True)
def _fresh_session(monkeypatch):
    """A session per test. `SESSION` is a process-lifetime singleton in
    production, which is right there and wrong here."""
    session = termpty.TermSession()
    monkeypatch.setattr(termpty, "SESSION", session)
    monkeypatch.setattr("app.web.routers.terminal.SESSION", session)
    yield session
    session.close()


def test_terminal_origin_allows_the_shell_and_loopback_only():
    assert terminal_origin_is_allowed(None)
    assert terminal_origin_is_allowed("tauri://localhost")
    assert terminal_origin_is_allowed("http://127.0.0.1:8787")
    assert not terminal_origin_is_allowed("chrome-extension://abc")
    assert not terminal_origin_is_allowed("moz-extension://abc")
    assert not terminal_origin_is_allowed("https://evil.example")
    assert not terminal_origin_is_allowed("null")


def test_an_extension_origin_is_refused_with_a_reason(tmp_path):
    """The global `only_from_here` middleware lets extensions reach every other
    route in this app. A shell is not every other route."""
    client = _client(tmp_path)
    for path in ("/api/terminal/state", "/api/terminal/stream"):
        response = client.get(path, headers={"origin": "chrome-extension://abc"})
        assert response.status_code == 403
        assert "not allowed" in response.json()["detail"]


def test_a_rejected_origin_says_which_origin(tmp_path):
    client = _client(tmp_path)
    response = client.get(
        "/api/terminal/state", headers={"origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert "evil.example" in response.json()["detail"]


def test_a_start_failure_is_reported_without_any_live_connection(tmp_path, monkeypatch):
    """The whole point of dropping the socket.

    Six releases were spent making a failure reach a client that had to be
    connected at the instant it happened. Here it is a field: one ordinary GET
    names it, and it does not matter who was watching.
    """
    def boom(*args, **kwargs):
        raise OSError("no such shell")

    monkeypatch.setattr(termpty.TermSession, "start", boom)
    client = _client(tmp_path)
    body = client.get("/api/terminal/state").json()
    assert "no such shell" in body["failure"]


def test_the_stream_reports_a_start_failure_and_then_ends(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("winpty-agent.exe is missing")

    monkeypatch.setattr(termpty.TermSession, "start", boom)
    client = _client(tmp_path)
    with client.stream("GET", "/api/terminal/stream") as response:
        assert response.status_code == 200
        frames = [
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]
    assert frames[0]["type"] == "error"
    assert "winpty-agent" in frames[0]["message"]


def test_input_answers_with_the_reason_it_could_not_be_delivered(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("the pty is gone")

    monkeypatch.setattr(termpty.TermSession, "start", boom)
    client = _client(tmp_path)
    response = client.post("/api/terminal/input", json={"data": "ls\n"})
    assert response.status_code == 503
    assert "the pty is gone" in response.json()["detail"]


def test_a_real_shell_echoes_what_was_typed(tmp_path, _fresh_session):
    """End to end over HTTP, on a real pty, with no socket anywhere.

    The one test that would have caught B107/B109 at the transport level if it
    had existed: it asks the same questions the panel asks, in the same order.
    """
    pytest.importorskip("ptyprocess")
    client = _client(tmp_path)

    first = client.get("/api/terminal/state").json()
    assert first["failure"] == ""
    assert first["running"] is True

    assert client.post("/api/terminal/input", json={"data": "echo kriko-ok\n"}).status_code == 200

    deadline = time.time() + 10
    seen = ""
    offset = 0
    while time.time() < deadline and "kriko-ok" not in seen:
        body = client.get(f"/api/terminal/state?offset={offset}").json()
        seen += body["data"]
        offset = body["offset"]
        time.sleep(0.05)
    assert "kriko-ok" in seen


def test_the_transcript_outlives_the_reader_looking_away(_fresh_session):
    """Output produced while nothing is connected is still there afterwards.

    The socket could not do this at all: bytes read with no client attached
    went nowhere. It is why a reader who opened the panel after a shell died
    saw a blank screen rather than its dying words.
    """
    session = _fresh_session
    session._append("before anyone was watching\n")
    chunk, offset, dropped = session.since(0)
    assert chunk == "before anyone was watching\n"
    assert offset == len(chunk)
    assert dropped is False


def test_a_consumer_that_fell_behind_is_told_so(_fresh_session):
    session = termpty.TermSession(scrollback=16)
    session._append("x" * 64)
    chunk, offset, dropped = session.since(0)
    assert dropped is True
    assert len(chunk) == 16
    assert offset == 64


# ── what the 0.8.0 Windows install reported ─────────────────────────────

class _WindowsLikePty:
    """A pty that answers the way `pywinpty` does, not the way `ptyprocess` does.

    The whole of the 0.8.0 Windows terminal bug is this difference.
    `ptyprocess.read()` blocks until there is something and raises `EOFError`
    at the end, so an empty return never happens. `pywinpty.read()` comes back
    with `''` the moment there is nothing *yet* — which on a freshly spawned
    `cmd.exe` is immediately, before it has written its banner.
    """

    def __init__(self, quiet_reads: int = 3):
        self.quiet_reads = quiet_reads
        self.reads = 0
        self.alive = True
        self.exitstatus = None
        self.written: list[str] = []

    def read(self, size=1024):
        self.reads += 1
        if not self.alive:
            raise EOFError("Pty is closed")
        if self.reads <= self.quiet_reads:
            return ""  # nothing to say *yet*
        return "C:\\Users\\reader>"

    def isalive(self):
        return self.alive

    def write(self, data):
        self.written.append(data)

    def setwinsize(self, rows, cols):
        pass

    def terminate(self, force=False):
        self.alive = False

    def close(self, force=False):
        self.alive = False


def test_a_quiet_pty_is_not_a_closed_one(monkeypatch, _fresh_session):
    """The Windows bug, as a test.

    An empty read was treated as end-of-file, so the reader thread ended the
    session before the shell had said anything — and the next read then raised
    the `EOFError: Pty is closed` the reader actually saw. The session must
    survive a shell that is merely quiet.
    """
    session = _fresh_session
    pty = _WindowsLikePty(quiet_reads=3)
    monkeypatch.setattr(termpty.TermSession, "_spawn", lambda self, c, r: pty, raising=False)
    session._start_locked = lambda cols=80, rows=24: _install(session, pty)
    _install(session, pty)

    deadline = time.time() + 5
    while time.time() < deadline and not session.since(0)[0]:
        time.sleep(0.05)

    state = session.state()
    assert session.since(0)[0], "the shell spoke and nothing recorded it"
    assert state["ended"] is False, "a quiet pty was mistaken for a closed one"
    assert state["failure"] == ""


def _install(session, pty):
    """Attach a fake pty to a session the way `start` would."""
    import threading

    with session._lock:
        session.proc = pty
        session.shell = "cmd.exe"
        session.failure = ""
        session.ended = False
        session._generation += 1
        generation = session._generation
    thread = threading.Thread(
        target=session._pump, args=(pty, generation), daemon=True
    )
    thread.start()
    session._reader = thread


def test_a_shell_that_exits_after_speaking_is_not_an_error(_fresh_session):
    """`exit` is an ordinary thing to type. It must not read as a fault."""
    session = _fresh_session
    pty = _WindowsLikePty(quiet_reads=0)
    _install(session, pty)
    deadline = time.time() + 5
    while time.time() < deadline and not session.since(0)[0]:
        time.sleep(0.05)
    pty.alive = False
    pty.exitstatus = 0

    deadline = time.time() + 5
    while time.time() < deadline and not session.state()["ended"]:
        time.sleep(0.05)
    state = session.state()
    assert state["ended"] is True
    assert state["failure"] == "", f"a clean exit reported as a failure: {state['failure']}"


def test_a_shell_that_dies_without_speaking_says_which_shell_and_how(_fresh_session):
    """`EOFError: Pty is closed` names neither the shell nor its exit status,
    which is why the first Windows report could not be acted on."""
    session = _fresh_session
    pty = _WindowsLikePty(quiet_reads=0)
    pty.alive = False
    pty.exitstatus = 1
    _install(session, pty)

    deadline = time.time() + 5
    while time.time() < deadline and not session.state()["failure"]:
        time.sleep(0.05)
    failure = session.state()["failure"]
    assert "cmd.exe" in failure, failure
    assert "status 1" in failure, failure
    assert "without producing any output" in failure, failure


def test_restart_gives_a_new_shell_and_a_clean_transcript(tmp_path, _fresh_session):
    pytest.importorskip("ptyprocess")
    client = _client(tmp_path)
    assert client.get("/api/terminal/state").json()["running"] is True

    deadline = time.time() + 10
    while time.time() < deadline and not _fresh_session.since(0)[0]:
        time.sleep(0.05)
    assert _fresh_session.state()["offset"] > 0

    body = client.post("/api/terminal/restart", json={"cols": 80, "rows": 24}).json()
    assert body["ended"] is False
    assert body["failure"] == ""
    # The transcript went with the old shell: a client still holding byte 400
    # of a session that no longer exists would wait forever.
    assert body["offset"] < 400


def test_close_ends_a_running_shell_and_it_stays_ended(tmp_path, _fresh_session):
    """The tab-close case: the reader is done, not restarting, not typing
    `exit`. It must free the process and must not come back on its own."""
    pytest.importorskip("ptyprocess")
    client = _client(tmp_path)
    assert client.get("/api/terminal/state").json()["running"] is True

    body = client.post("/api/terminal/close").json()
    assert body["ended"] is True
    assert body["running"] is False

    # A client that keeps polling after closing the tab must not find a shell
    # quietly running again underneath it.
    again = client.get("/api/terminal/state").json()
    assert again["ended"] is True
    assert again["running"] is False


def test_close_before_anything_ever_started_still_sticks(_fresh_session):
    """Closing a tab that never opened a shell must not leave the session
    startable again on the next poll."""
    session = _fresh_session
    assert session.proc is None
    session.close()
    assert session.state()["ended"] is True


def test_an_ended_session_is_not_silently_resurrected(monkeypatch, tmp_path, _fresh_session):
    """The polling client asks twice a second. If `/state` restarted the shell,
    a deliberate `exit` would come straight back and the one signal saying it
    is gone would never live long enough to be rendered."""
    client = _client(tmp_path)
    _fresh_session._end()
    body = client.get("/api/terminal/state").json()
    assert body["ended"] is True


def test_a_momentarily_unresponsive_pty_is_not_declared_dead(_fresh_session):
    """One `isalive()` sample is weak evidence for a strong verdict.

    The failure it produces — "exited without producing any output" — is
    indistinguishable from the real thing, so a pty that answers `False` once
    just after spawning would end the terminal for a reason nobody could
    argue with. It is sampled twice with a gap instead.
    """
    session = _fresh_session

    class _FlickeringPty(_WindowsLikePty):
        def __init__(self):
            super().__init__(quiet_reads=99)
            self.alive_calls = 0

        def isalive(self):
            self.alive_calls += 1
            # Dead on the first ask, alive ever after — a spawn that had not
            # finished settling.
            return self.alive_calls != 1

    pty = _FlickeringPty()
    _install(session, pty)
    deadline = time.time() + 5
    while time.time() < deadline and pty.alive_calls < 2:
        time.sleep(0.02)
    time.sleep(0.2)

    state = session.state()
    assert state["ended"] is False, f"one bad sample ended the session: {state}"
    assert state["failure"] == ""


def test_an_idle_shell_backs_off_and_a_keystroke_brings_it_back(_fresh_session):
    """The efficiency half, and the reason it cannot simply be a slow poll.

    A shell at its prompt must not cost fifty wake-ups a second for as long as
    the app is open; a keystroke's echo must not arrive a fifth of a second
    late. `write` resets the clock, so typing is always on the fast interval.
    """
    session = _fresh_session
    session._busy = time.monotonic() - (termpty.IDLE_PATIENCE + 1)
    assert time.monotonic() - session._busy > termpty.IDLE_PATIENCE

    class _Quiet:
        def write(self, data):
            pass

    session.proc = _Quiet()
    session.write("x")
    assert time.monotonic() - session._busy < termpty.IDLE_PATIENCE, (
        "a keystroke left the reader on the slow interval"
    )
