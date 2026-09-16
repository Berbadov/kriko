"""The config the app hands out has to be a command that runs.

A snippet the reader pastes and that then fails is worse than no snippet: the
error surfaces in their harness, hours later, about a file they did not write.
So this suite does not check the *shape* of the block — it runs it.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.routers.agent import command_for
from app.web.settings import Settings


def _client(tmp_path):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


def test_the_block_names_the_store_this_window_reads(tmp_path):
    """An agent on a different SQLite file looks exactly like success.

    Findings land, the window shows nothing, and there is no error anywhere in
    between. The store path is therefore explicit in the command rather than
    left to whichever `~/.kriko` the harness happens to resolve.
    """
    body = _client(tmp_path).get("/api/agent-config").json()
    server = body["mcp_json"]["mcpServers"]["kriko"]
    assert str(tmp_path / "knowledge.sqlite") in server["args"]
    assert body["store"] == str(tmp_path / "knowledge.sqlite")
    assert server["type"] == "stdio"


def test_the_advertised_command_actually_speaks_mcp(tmp_path):
    """Run what we tell the reader to run, and complete a handshake with it."""
    server = _client(tmp_path).get("/api/agent-config").json()["mcp_json"][
        "mcpServers"
    ]["kriko"]
    process = subprocess.Popen(
        [server["command"], *server["args"]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={"PATH": "/usr/bin:/bin", **server.get("env", {})},
    )
    try:
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "0"},
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        deadline = time.time() + 30
        answer = None
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            try:
                answer = json.loads(line)
            except ValueError:
                continue
            break
        assert answer is not None, (
            "the command in /api/agent-config answered nothing:\n"
            + (process.stderr.read() or "(no stderr)")
        )
        assert answer["result"]["serverInfo"]["name"] == "kriko"
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()
            process.wait(timeout=10)
    # No store file is asserted here: `initialize` opens no connection, and a
    # test that made it do so would be testing MCP rather than this config.


def test_a_frozen_app_advertises_itself_and_not_an_interpreter(monkeypatch, tmp_path):
    """Frozen, there is no `python` on the reader's machine to invoke.

    The two branches are not two paths to the same command — the frozen binary
    is its own entry point and takes `--mcp` directly, and an installed reader
    has no `-m` to give anything.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/Kriko/kriko-sidecar")
    entry = command_for(tmp_path / "knowledge.sqlite")
    assert entry["frozen"] is True
    assert entry["command"].endswith("kriko-sidecar")
    assert entry["args"][0] == "--mcp"
    assert "-m" not in entry["args"], "a frozen app has no interpreter to pass -m to"
    assert entry["env"] == {}, "PYTHONPATH means nothing to a frozen binary"


def test_on_windows_the_written_command_carries_its_own_survival_kit(monkeypatch, tmp_path):
    """The bug live reports call "cannot connect to the server: kriko": a
    harness on Windows that does not merge its own environment into the
    config's `env` spawns a process with none of `SystemRoot`/`TEMP`, which a
    plain interpreter or a PyInstaller onefile cannot survive — before a
    single byte of our JSON-RPC frame is ever written. This must not depend on
    the harness inheriting anything."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("TEMP", "C:\\Users\\r\\AppData\\Local\\Temp")

    interpreted = command_for(tmp_path / "knowledge.sqlite")
    assert interpreted["env"]["SystemRoot"] == "C:\\Windows"
    assert interpreted["env"]["TEMP"]
    assert "PYTHONPATH" in interpreted["env"], "still needed to find app.sidecar"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\Program Files\\Kriko\\kriko-sidecar.exe")
    frozen = command_for(tmp_path / "knowledge.sqlite")
    assert frozen["env"]["SystemRoot"] == "C:\\Windows"


def test_the_named_tools_exist_on_the_server():
    """The three names the UI shows are the three an agent cannot work without."""
    from app import mcp_server

    body = Path(mcp_server.__file__).read_text()
    for tool in ("research_brief", "coverage_gaps", "submit_findings"):
        assert f"def {tool}" in body, f"{tool} is advertised but not implemented"


# ── the one-click path ──────────────────────────────────────────────────
#
# `_home` is redirected in every one of these. A test that wires the machine
# it is running on would pass and then silently edit the author's own
# ~/.claude.json, which is precisely the damage this feature has to be trusted
# not to do.


def test_every_known_harness_is_listed_with_its_state(tmp_path, monkeypatch):
    from app import agentconfig

    monkeypatch.setattr(agentconfig, "_home", lambda: tmp_path / "home")
    body = _client(tmp_path).get("/api/agent-targets").json()

    assert {t["id"] for t in body["targets"]} >= {"claude-code", "cursor"}
    assert all(t["state"] == "absent" for t in body["targets"])
    assert body["store"].endswith("knowledge.sqlite")


def test_connecting_writes_a_config_the_harness_can_read(tmp_path, monkeypatch):
    from app import agentconfig

    home = tmp_path / "home"
    monkeypatch.setattr(agentconfig, "_home", lambda: home)
    client = _client(tmp_path)

    assert client.post("/api/agent-targets/claude-code/connect").json()["state"] == "connected"

    written = json.loads((home / ".claude.json").read_text())["mcpServers"]["kriko"]
    assert written == client.get("/api/agent-config").json()["mcp_json"]["mcpServers"]["kriko"]


def test_the_listing_reflects_a_connection_that_was_just_made(tmp_path, monkeypatch):
    from app import agentconfig

    monkeypatch.setattr(agentconfig, "_home", lambda: tmp_path / "home")
    client = _client(tmp_path)
    client.post("/api/agent-targets/cursor/connect")

    states = {t["id"]: t["state"] for t in client.get("/api/agent-targets").json()["targets"]}
    assert states["cursor"] == "connected"
    assert states["claude-code"] == "absent"


def test_a_harness_this_build_does_not_know_is_a_404(tmp_path):
    assert _client(tmp_path).post("/api/agent-targets/emacs/connect").status_code == 404


def test_a_config_the_reader_broke_is_refused_and_left_alone(tmp_path, monkeypatch):
    from app import agentconfig

    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text("{broken")
    monkeypatch.setattr(agentconfig, "_home", lambda: home)

    response = _client(tmp_path).post("/api/agent-targets/claude-code/connect")
    assert response.status_code == 409
    assert (home / ".claude.json").read_text() == "{broken"


def test_verify_actually_starts_the_thing_it_advertised(tmp_path):
    """The reader's question after Connect is "does it work", not "was it
    written" — and those fail separately, for different reasons."""
    body = _client(tmp_path).post("/api/agent-verify").json()
    assert body["ok"] is True
    assert body["server"] == "kriko"
    # `initialize` answering is not the reader's question — a server that
    # exposes no tools is exactly as useless as one that never started, so
    # verify must have gone one step further and asked.
    assert "research_brief" in body["tools"]
    assert "submit_findings" in body["tools"]


def test_verify_lists_every_tool_the_server_actually_registers(tmp_path):
    """The registry, not a guess — the same source `registered_tools()` reads
    in `test_mcp_server.py`, so a tool renamed on one side shows up here."""
    from app import mcp_server

    body = _client(tmp_path).post("/api/agent-verify").json()
    assert set(body["tools"]) == mcp_server.registered_tools()


def test_verify_reports_a_command_that_cannot_start_rather_than_raising(tmp_path):
    from app import agentconfig

    row = agentconfig.handshake({"command": str(tmp_path / "nope"), "args": []})
    assert row["ok"] is False
    assert row["detail"]


def test_verify_runs_the_command_in_a_real_environment(monkeypatch):
    """A diagnostic that strips the environment tests a situation nobody is in.

    `handshake` used to hand the child `{"PATH": ...}` and nothing else. On
    Windows that kills a PyInstaller onefile binary before it parses an
    argument — it unpacks itself through `TEMP`/`TMP` — and the reader is told

        [PYI-24700:ERROR] Could not create temporary directory!

    under a heading asking whether *their* agent works. It was ours. Harnesses
    inherit the environment and overlay the config's `env`; so does this now.
    """
    from app.agentconfig import _launch_environment

    monkeypatch.setenv("TEMP", "/somewhere")
    monkeypatch.setenv("KRIKO_STORE", "/inherited")
    built = _launch_environment({"KRIKO_STORE": "/declared"})

    assert built["TEMP"] == "/somewhere", "the harness's environment is inherited"
    assert built["KRIKO_STORE"] == "/declared", "the config's env still wins"
