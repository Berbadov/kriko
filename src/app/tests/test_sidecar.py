"""The handshake the desktop shell depends on.

The shell has exactly one way to learn where the server is: the first line of
the sidecar's stdout. If that line moves, changes shape, or arrives after the
server is already serving, the app shows a blank window and there is nothing in
it to explain why. So it is pinned here rather than trusted.

These tests run the real module in a real subprocess. A mocked uvicorn would
pass while the two things most likely to break — buffered stdout in a frozen
binary, and a port announced before it is held — went unnoticed.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from app.sidecar import PORT_LINE, reserve


def test_reserve_returns_a_port_that_is_already_bound():
    """Announcing a port we do not hold is the race this avoids."""
    sock, port = reserve("127.0.0.1", 0)
    try:
        assert port > 0
        with pytest.raises(OSError):
            second, _ = reserve("127.0.0.1", port)
            second.close()
    finally:
        sock.close()


def test_an_explicit_port_is_honoured():
    sock, port = reserve("127.0.0.1", 0)
    sock.close()
    again, chosen = reserve("127.0.0.1", port)
    try:
        assert chosen == port
    finally:
        again.close()


@pytest.fixture
def sidecar(tmp_path):
    env = {
        "KRIKO_STORE": str(tmp_path / "knowledge.sqlite"),
        "KRIKO_APP_STATE": str(tmp_path / "app.sqlite"),
        "KRIKO_ANALYSES_LOG": str(tmp_path / "analyses.jsonl"),
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": "src",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "app.sidecar"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover — belt and braces
            process.kill()
            process.wait(timeout=10)


def test_the_first_line_of_stdout_is_the_port_and_the_server_is_reachable(sidecar):
    line = sidecar.stdout.readline().strip()
    assert line.startswith(PORT_LINE), line
    port = int(line.split()[1])

    deadline = time.time() + 20
    body = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=1
            ) as response:
                body = json.load(response)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.1)
    assert body is not None, "the sidecar announced a port it never served"
    assert body["ok"] is True
    # Both SQLite paths, because an operator who can only see one of them
    # cannot tell which file their history is in.
    assert body["store"] and body["app_state"]


def test_terminating_the_sidecar_leaves_nothing_holding_the_port(sidecar):
    """An orphaned uvicorn holding a WAL lock is the packaging failure mode."""
    port = int(sidecar.stdout.readline().strip().split()[1])
    sidecar.terminate()
    sidecar.wait(timeout=15)

    deadline = time.time() + 10
    while time.time() < deadline:
        sock = None
        try:
            sock, _ = reserve("127.0.0.1", port)
            return  # the port came back, so nothing is still listening
        except OSError:
            time.sleep(0.2)
        finally:
            if sock is not None:
                sock.close()
    raise AssertionError(f"port {port} is still held after the sidecar exited")
