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
from pathlib import Path
import time
import urllib.error
import urllib.request

import pytest

from app.sidecar import EXTRA_LINE, PORT_LINE, reserve


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


def _env(tmp_path):
    return {
        "KRIKO_STORE": str(tmp_path / "knowledge.sqlite"),
        "KRIKO_APP_STATE": str(tmp_path / "app.sqlite"),
        "KRIKO_ANALYSES_LOG": str(tmp_path / "analyses.jsonl"),
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": "src",
    }


@pytest.fixture
def sidecar(tmp_path):
    env = _env(tmp_path)
    process = subprocess.Popen(
        # `--extension-port 0`: the fixed port is exercised on purpose below,
        # and a fixture that takes it would make every other test in the file
        # depend on what else is running on this machine.
        [sys.executable, "-m", "app.sidecar", "--extension-port", "0"],
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


def test_the_sidecar_exits_when_its_parent_goes_away(tmp_path):
    """The orphan that breaks the *installer*, not just the next launch.

    A sidecar that outlives the shell keeps its own binary mapped on Windows,
    and the next install stops on "Error opening file for writing:
    kriko-sidecar.exe" — a message that names the file and not the cause. The
    shell passing `--exit-with-parent` is what makes that unreachable, so the
    behaviour is tested by actually losing the pipe rather than by mocking one.
    """
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.sidecar",
            "--exit-with-parent",
            "--extension-port",
            "0",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
    )
    try:
        line = process.stdout.readline().strip()
        assert line.startswith(PORT_LINE), line

        # Closing our end of the pipe is precisely what a crashed shell does.
        # No signal is sent, and no handler in the child could have run.
        process.stdin.close()
        process.wait(timeout=20)
        assert process.returncode is not None
    finally:
        if process.poll() is None:  # pragma: no cover — the failure path
            process.kill()
            process.wait(timeout=10)


def test_the_watchdog_is_off_unless_asked(tmp_path):
    """`< /dev/null` in a terminal must not be an instant exit.

    The flag exists because stdin has three different meanings here — a tty, a
    pipe from the shell, and nothing at all — and only the second one carries
    the parent's lifetime. Defaulting to on would make the operator's own
    `python -m app.sidecar` unusable under nohup, cron, or a systemd unit.
    """
    process = subprocess.Popen(
        [sys.executable, "-m", "app.sidecar", "--extension-port", "0"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
    )
    try:
        assert process.stdout.readline().strip().startswith(PORT_LINE)
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=3)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()
            process.wait(timeout=10)


def _health(port: int, timeout: float = 20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=1
            ) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.1)
    return None


def test_the_extension_port_is_served_as_well_as_the_announced_one(tmp_path):
    """Two doors, one server.

    The extension hardcodes a port because nothing can hand it one — it has no
    filesystem and no channel from the window. Before this the desktop app was
    only ever on an OS-chosen port, so the extension could not reach it at all,
    and the symptom was an extension that worked against `python -m app.web`
    and silently did nothing against the installed app.
    """
    sock, free = reserve("127.0.0.1", 0)
    sock.close()  # a port nobody holds, standing in for the fixed one
    process = subprocess.Popen(
        [sys.executable, "-m", "app.sidecar", "--extension-port", str(free)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
    )
    try:
        announced = int(process.stdout.readline().strip().split()[1])
        second = process.stdout.readline().strip()
        assert second.startswith(EXTRA_LINE), second
        assert int(second.split()[1]) == free
        assert announced != free

        for port in (announced, free):
            body = _health(port)
            assert body is not None, f"nothing served on {port}"
            assert body["ok"] is True
    finally:
        process.terminate()
        process.wait(timeout=15)


def test_a_taken_extension_port_is_not_fatal(tmp_path):
    """A second instance, or a terminal already on 8787, must still open.

    The app has the port it needs before this bind is attempted. Treating a
    convenience socket as a startup requirement would turn "the dashboard is
    already running" into "the app will not launch".
    """
    holder, taken = reserve("127.0.0.1", 0)
    process = subprocess.Popen(
        [sys.executable, "-m", "app.sidecar", "--extension-port", str(taken)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
    )
    try:
        line = process.stdout.readline().strip()
        assert line.startswith(PORT_LINE), line
        body = _health(int(line.split()[1]))
        assert body is not None and body["ok"] is True
    finally:
        process.terminate()
        process.wait(timeout=15)
        holder.close()


def _rpc(process, message: dict) -> None:
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()


def _reply(process, timeout: float = 20.0):
    """Read lines until one is a JSON-RPC response with a result."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = process.stdout.readline()
        if not line:
            return None
        try:
            body = json.loads(line)
        except ValueError:
            continue  # a log line on stdout would be a bug, but not this test's
        if "result" in body or "error" in body:
            return body
    return None


def test_the_same_binary_serves_mcp_over_stdio(tmp_path):
    """The agent's door into an *installed* app.

    Before this, the research protocol only existed for someone with a source
    checkout: an installed reader had a Research button that produces a brief
    and nothing able to act on it. The handshake is spoken for real rather than
    mocked, because what breaks in the frozen binary is exactly the dynamic
    imports FastMCP does at startup — and that fails identically to a hang.
    """
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.sidecar",
            "--mcp",
            "--store",
            str(tmp_path / "knowledge.sqlite"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
    )
    try:
        _rpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            },
        )
        hello = _reply(process)
        assert hello is not None, "the MCP server never answered initialize"
        assert hello.get("result", {}).get("serverInfo", {}).get("name") == "kriko"

        _rpc(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _rpc(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = _reply(process)
        assert listed is not None, "the MCP server never listed its tools"
        names = {tool["name"] for tool in listed["result"]["tools"]}
        # The acceptance path and the gap report: without both, an agent can
        # neither find work nor hand anything back.
        assert {"submit_findings", "coverage_gaps"} <= names, names
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()
            process.wait(timeout=10)


def test_an_unhandled_exception_in_a_route_reaches_the_app_log(tmp_path):
    """The gap that hid the real 0.7.5 terminal bug report from app.log.

    `uvicorn.Config`'s default `log_config` calls `logging.config.dictConfig`,
    which gives "uvicorn" its own stderr handler and `propagate=False`. An
    unhandled exception in any route is logged through the child logger
    "uvicorn.error", which — with no handler of its own — climbs to "uvicorn"
    and stops there, never reaching the root logger `app.logs.configure()`
    attached to `KRIKO_LOG`. It still prints to stderr, but nothing reads
    stderr once the shell's window has opened, so a reader's own report of a
    broken terminal came back with an `app.log` that had nothing in it about
    why.

    `SHELL` pointed at a binary that does not exist is a reliable way to make
    `TermSession.start()` raise without mocking anything: the terminal
    websocket handler runs it with no try/except, exactly as it did the day
    this went unlogged.
    """
    log_path = tmp_path / "app.log"
    env = _env(tmp_path)
    env["KRIKO_LOG"] = str(log_path)
    env["SHELL"] = str(tmp_path / "no-such-shell")
    process = subprocess.Popen(
        [sys.executable, "-m", "app.sidecar", "--extension-port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        line = process.stdout.readline().strip()
        assert line.startswith(PORT_LINE), line
        port = int(line.split()[1])
        assert _health(port) is not None, "the sidecar announced a port it never served"

        from websockets.sync.client import connect

        with pytest.raises(Exception):
            with connect(f"ws://127.0.0.1:{port}/api/terminal/ws") as ws:
                ws.recv(timeout=5)

        deadline = time.time() + 10
        text = ""
        while time.time() < deadline:
            if log_path.exists():
                text = log_path.read_text()
                if "uvicorn.error" in text:
                    break
            time.sleep(0.1)
        assert "Exception in ASGI application" in text, (
            f"the route's exception never reached app.log: {text!r}"
        )
    finally:
        process.terminate()
        process.wait(timeout=15)


def test_mcp_mode_prints_no_handshake_of_its_own(tmp_path):
    """stdout is the transport in MCP mode, so nothing else may write to it."""
    source = (Path(__file__).resolve().parents[1] / "sidecar.py").read_text()
    body = source.split("def main(")[1]
    dispatch = body.index("return serve_mcp")
    announce = body.index(f'print(f"{{PORT_LINE}}')
    assert dispatch < announce, (
        "the port is announced before the MCP dispatch — a stray line on stdout "
        "is a protocol error the client reports as malformed JSON"
    )
