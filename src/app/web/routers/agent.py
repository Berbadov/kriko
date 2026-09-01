"""How an agent reaches *this* installation.

The research protocol was always written down — `packs/<name>/research/`, the
MCP tool set, and `app/findings.py` refusing a quote it cannot find in the
document. What it never had was an **address**. `.mcp.json` in the repo points a
harness at a source checkout, so a reader who installed the app had a *Research*
button that produces a brief and nothing anywhere able to act on it.

This endpoint answers the one question that config cannot be written without:
which command, on this machine, is the MCP server for the store this window is
reading? Frozen, that is the app's own binary with `--mcp`; from a checkout it
is the interpreter running this process. The store path is passed explicitly in
both cases — an agent writing to a different SQLite file than the window reads
is the single failure that would look exactly like success.
"""

import sys
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["agent"])

#: What a harness has to be told, minus the paths, which are resolved per host.
SERVER_NAME = "kriko"


def command_for(store_path: Path) -> dict:
    """The command a harness should run, and why it is that one.

    `sys.frozen` is PyInstaller's marker. It matters here because the two cases
    have different shapes rather than different paths: the frozen binary *is*
    the entry point, while an interpreter needs the module name and a
    `PYTHONPATH` pointing at `src/`. Both go through `app.sidecar --mcp` rather
    than `app.mcp_server` directly, because that is the entry point that parses
    `--store` — the MCP module itself has no argv of its own, and a config that
    passed one would fail on the reader's machine and nowhere else.
    """
    store = ["--store", str(store_path)]
    if getattr(sys, "frozen", False):
        return {
            "command": str(Path(sys.executable).resolve()),
            "args": ["--mcp", *store],
            "env": {},
            "frozen": True,
        }
    # …/src/app/web/routers/agent.py → …/src
    src = Path(__file__).resolve().parents[3]
    return {
        # NOT resolved. `.venv/bin/python` is a symlink to the base interpreter,
        # and the resolved path has no venv on its import path: the advertised
        # command would die with `No module named 'fastapi'` on the reader's
        # machine. Only the frozen binary above is safe to canonicalise.
        "command": sys.executable,
        "args": ["-m", "app.sidecar", "--mcp", *store],
        "env": {"PYTHONPATH": str(src)},
        "frozen": False,
    }


@router.get("/agent-config")
def agent_config(request: Request):
    """A block that can be pasted into a harness without editing.

    Returned as data *and* as `mcp_json`, already shaped for `.mcp.json`, for
    the same reason the boot screen is plain HTML: the reader is one copy away
    from a working setup, and any transcription step is a step that goes wrong
    silently.
    """
    settings = request.app.state.settings
    entry = command_for(Path(settings.store_path))
    server = {"type": "stdio", "command": entry["command"], "args": entry["args"]}
    if entry["env"]:
        server["env"] = entry["env"]
    return {
        "server_name": SERVER_NAME,
        "frozen": entry["frozen"],
        "store": str(settings.store_path),
        "mcp_json": {"mcpServers": {SERVER_NAME: server}},
        # Named so the UI does not have to know the tool list to explain the
        # protocol: these are the two an agent cannot work without.
        "tools": ["research_brief", "coverage_gaps", "submit_findings"],
    }
