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


def test_the_named_tools_exist_on_the_server():
    """The three names the UI shows are the three an agent cannot work without."""
    from app import mcp_server

    body = Path(mcp_server.__file__).read_text()
    for tool in ("research_brief", "coverage_gaps", "submit_findings"):
        assert f"def {tool}" in body, f"{tool} is advertised but not implemented"
