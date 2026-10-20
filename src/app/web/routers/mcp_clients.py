"""The exact config a chat client needs to reach this Kriko, per client.

`agent.py` answers the question for coding agents and writes their config in
one press. A reader whose chat lives somewhere else (a desktop chat app, the
chat panel of an editor, a client that only takes a URL) needs the same
answer in that client's own shape, and needs to *see* it: pasting into the
wrong file, or into the wrong key (`servers` in one editor, `mcpServers` in
the rest), makes a client that appears connected and lists no tools.

So this does two things and nothing else:

* **shows** the snippet for each client, built from the same command the
  Agents screen would write (`agent.command_for`), so the two cannot name
  different engines or different stores;
* **writes** it for the clients whose config file is known, as the one-key
  merge `agentconfig.connect` already makes safe. The generic snippet and the
  URL form are shown, never written: there is no file to write them to.

The URL form is the optional local HTTP transport (`app/mcphttp.py`). Its
address is always 127.0.0.1; this endpoint has no way to say otherwise.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app import agentconfig, mcphttp
from app.web.routers import agent

router = APIRouter(prefix="/api", tags=["mcp"])


def _vscode_target() -> agentconfig.Target | None:
    """The editor chat's user-level MCP file. It calls the map `servers`."""
    home = agentconfig._home()
    if sys.platform == "darwin":
        path: Path | None = home / "Library/Application Support/Code/User/mcp.json"
    elif sys.platform == "win32":
        base = agentconfig._appdata()
        path = base / "Code/User/mcp.json" if base else None
    else:
        path = home / ".config/Code/User/mcp.json"
    if path is None:
        return None
    return agentconfig.Target("vscode", "VS Code chat", path, key="servers")


#: client id -> (label, what it is, the agentconfig target id or None)
#: A small closed list of client *shapes*, not data that grows with coverage.
_FILE_CLIENTS = (
    ("desktop", "Desktop chat app", "claude-desktop",
     "Claude Desktop reads this file at start-up; restart it after writing."),
    ("ide", "IDE chat", "cursor",
     "Cursor's global MCP file. Restart the chat panel after writing."),
    ("vscode", "VS Code chat", "vscode",
     "VS Code's user MCP file, which names its map `servers`."),
)


def _target(target_id: str) -> agentconfig.Target | None:
    if target_id == "vscode":
        return _vscode_target()
    return agentconfig.by_id(target_id)


def _start_command(server: dict) -> str:
    """The stdio command with the one flag that makes it serve a URL instead."""
    args = list(server["args"])
    args.insert(args.index("--mcp") + 1, "--mcp-http")
    argv = [server["command"], *args]
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def _snippet(key: str, server: dict) -> str:
    return json.dumps({key: {agent.SERVER_NAME: server}}, indent=2)


def _clients(settings) -> list[dict]:
    server = agent._server_block(settings)
    store = Path(settings.store_path)
    rows: list[dict] = [{
        "id": "generic",
        "label": "Any MCP client",
        "note": "Add this to the client's MCP servers. Where it goes depends on the client.",
        "snippet": _snippet(agentconfig.SERVER_KEY, server),
        "path": "",
        "writable": False,
        "state": "shown",
    }]
    for client_id, label, target_id, note in _FILE_CLIENTS:
        target = _target(target_id)
        if target is None or target.path is None:
            continue
        status = agentconfig.status_of(target, server_name=agent.SERVER_NAME, store_path=store)
        rows.append({
            "id": client_id,
            "label": label,
            "note": note,
            "snippet": _snippet(target.key, server),
            "path": str(target.path),
            "writable": status["state"] != "unreadable",
            "state": status["state"],
            **({"detail": status["detail"]} if status.get("detail") else {}),
        })
    rows.append({
        "id": "url",
        "label": "A client that needs a URL",
        "note": ("Start Kriko's local server with the command below, then give the client "
                 "this address. It answers on this machine only."),
        "snippet": json.dumps({agentconfig.SERVER_KEY: {agent.SERVER_NAME: {"url": mcphttp.url()}}},
                              indent=2),
        "path": "",
        "writable": False,
        "state": "shown",
        "start": _start_command(server),
    })
    return rows


@router.get("/mcp-clients")
def mcp_clients(request: Request):
    """Every client shape, with its snippet and whether this machine has it wired."""
    settings = request.app.state.settings
    entry = agent.command_for(Path(settings.store_path))
    return {
        "server_name": agent.SERVER_NAME,
        "store": str(settings.store_path),
        "command": entry["command"],
        "frozen": entry["frozen"],
        "url": mcphttp.url(),
        "clients": _clients(settings),
    }


@router.post("/mcp-clients/{client_id}/write")
def write_mcp_client(client_id: str, request: Request):
    """Merge Kriko into one client's config file. A 409 names a file the reader broke."""
    known = {cid: tid for cid, _label, tid, _note in _FILE_CLIENTS}
    if client_id not in known:
        # Includes the two show-only shapes: there is nowhere to write them.
        raise HTTPException(404, f"nothing to write for {client_id!r}")
    target = _target(known[client_id])
    if target is None or target.path is None:
        raise HTTPException(404, f"{client_id} has no config location on this platform")
    settings = request.app.state.settings
    try:
        agentconfig.connect(target, server_name=agent.SERVER_NAME,
                            server=agent._server_block(settings))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"could not write {target.path}: {exc}") from exc
    return agentconfig.status_of(target, server_name=agent.SERVER_NAME,
                                 store_path=Path(settings.store_path)) | {"id": client_id}
