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
