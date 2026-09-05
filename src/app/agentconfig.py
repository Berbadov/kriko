"""Writing this installation's address into a harness's config, safely.

`/api/agent-config` answers *which command*; this answers *where it goes*. The
gap between those two was a paragraph of documentation and a copy-paste, which
is the step that goes wrong silently: a reader who pastes into the wrong file,
or into a file whose JSON they then break, gets an agent that appears to be
connected and writes findings to a store nobody reads.

Three rules hold everything here together:

* **Never author a config file's other contents.** A harness config holds the
  reader's other servers, their API keys, their preferences. Every write here
  is a merge of exactly one key under `mcpServers`, re-serialised from what was
  parsed — never a template rendered over the top.
* **Fail open, one target at a time.** A harness that is not installed, whose
  config is unreadable, or whose JSON is malformed is *reported*, not raised:
  the reader has three other harnesses and is entitled to see the state of all
  of them.
* **Being "connected" is about the store, not the key.** A `kriko` entry
  pointing at a different `knowledge.sqlite` is the failure that looks exactly
  like success, so it reports as `stale`, not `connected`.

The target table is a small closed vocabulary — coding harnesses, a fixed
engineering category, not data that grows with pack coverage.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SERVER_KEY = "mcpServers"


@dataclass(frozen=True)
class Target:
    """A harness, and the file it reads its MCP servers out of."""

    id: str
    label: str
    #: Where the config lives, or None on a platform where this harness has no
    #: home. A `None` target is dropped from the listing rather than shown
    #: broken.
    path: Path | None
    #: The key the server map lives under. `mcpServers` everywhere except VS
    #: Code, which calls it `servers` — one word, and a config written under
    #: the wrong one is silently ignored.
    key: str = SERVER_KEY


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _claude_desktop_path() -> Path | None:
    """Claude Desktop stores its config in the platform's app-data directory.

    Three different conventions for one file. Getting this wrong writes a
    config nothing reads, which is why it is one function rather than an
    expression at the call site.
    """
    home = _home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / "Claude/claude_desktop_config.json" if base else None
    return home / ".config/Claude/claude_desktop_config.json"


def targets() -> list[Target]:
    """Every harness this build knows how to wire, in the order to show them."""
    home = _home()
    found = [
        Target("claude-code", "Claude Code", home / ".claude.json"),
        Target("claude-desktop", "Claude Desktop", _claude_desktop_path()),
        Target("cursor", "Cursor", home / ".cursor/mcp.json"),
        Target("vscode", "VS Code", home / ".vscode/mcp.json", key="servers"),
    ]
    return [t for t in found if t.path is not None]


def _load(path: Path) -> tuple[dict, str | None]:
    """Parse a config, or say why it could not be.

    A missing file is not an error — it is the ordinary state before a reader
    has ever configured that harness, and writing one is exactly what Connect
    is for.
    """
    if not path.exists():
        return {}, None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"unreadable: {exc.strerror or exc}"
    if not text.strip():
        return {}, None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"not valid JSON (line {exc.lineno})"
    if not isinstance(parsed, dict):
        return {}, "not a JSON object"
    return parsed, None


def _servers(config: dict, target: Target) -> dict:
    servers = config.get(target.key)
    return servers if isinstance(servers, dict) else {}


def status_of(target: Target, *, server_name: str, store_path: Path) -> dict:
    """What state this harness is in, without changing anything.

    `stale` is the state worth having: an entry exists, so a reader would call
    it connected, but it does not name the store this window is reading.
    """
    row = {
        "id": target.id,
        "label": target.label,
        "path": str(target.path),
        "exists": target.path.exists(),
    }
    config, problem = _load(target.path)
    if problem:
        return {**row, "state": "unreadable", "detail": problem}
    entry = _servers(config, target).get(server_name)
    if not isinstance(entry, dict):
        return {**row, "state": "absent"}
    args = [str(a) for a in entry.get("args", [])]
    if str(store_path) in args:
        return {**row, "state": "connected"}
    return {
        **row,
        "state": "stale",
        "detail": "points at a different store than this window is reading",
    }


def connect(target: Target, *, server_name: str, server: dict) -> dict:
    """Merge one server entry into a harness config, leaving the rest alone.

    Written to a sibling temp file and replaced, because the failure this
    guards against is not a wrong value — it is a half-written config, which
    takes the reader's *other* servers down with it.
    """
    if target.path is None:
        raise ValueError(f"{target.id} has no config location on this platform")
    config, problem = _load(target.path)
    if problem:
        raise ValueError(f"{target.path}: {problem}")

    servers = config.get(target.key)
    if not isinstance(servers, dict):
        servers = {}
        config[target.key] = servers
    servers[server_name] = server

    target.path.parent.mkdir(parents=True, exist_ok=True)
    temp = target.path.with_suffix(target.path.suffix + ".kriko-tmp")
    temp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, target.path)
    return {"id": target.id, "path": str(target.path), "state": "connected"}


#: Where each harness looks for skills. Absent for a harness with no skill
#: mechanism — the MCP connection still works there, the agent is simply not
#: told *when* to use it, which is a smaller loss than writing a file that
#: nothing reads.
SKILL_DIRS = {
    "claude-code": ".claude/skills",
}


def skill_path(target: Target, name: str) -> Path | None:
    relative = SKILL_DIRS.get(target.id)
    return _home() / relative / name / "SKILL.md" if relative else None


def write_skill(target: Target, name: str, body: str) -> str | None:
    """Install the research skill for a harness that has somewhere to put it.

    Overwritten rather than merged, unlike a config: this file has one author,
    and it is regenerated from the installed packs every time so that an
    updated pack updates the protocol.
    """
    path = skill_path(target, name)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".kriko-tmp")
    temp.write_text(body, encoding="utf-8")
    os.replace(temp, path)
    return str(path)


def by_id(target_id: str) -> Target | None:
    return next((t for t in targets() if t.id == target_id), None)


def _launch_environment(extra: dict) -> dict:
    """The environment a *harness* would start this command in.

    An earlier version handed the child `{"PATH": ...}` and nothing else, on the
    theory that a minimal environment is a more honest test. It is the opposite:
    it tests a situation no harness creates, and it fails for reasons the
    advertised command never would.

    On Windows it failed outright. A PyInstaller onefile binary is an archive
    that unpacks itself into a temporary directory before any of our code runs,
    and it finds that directory through `TEMP`/`TMP`. Strip those and the
    process dies before `--mcp` is ever parsed, with

        [PYI-24700:ERROR] Could not create temporary directory!

    reported to the reader as *their* configuration being broken. It was ours.
    `SystemRoot` is the same class of variable and its absence breaks sockets.

    So: inherit the environment, then overlay what the config declares. That is
    what Claude Code, Cursor and the rest do when they spawn a stdio server, and
    a diagnostic is only worth running if it runs the real thing. Note that
    `packaging/smoke_sidecar.py` has always launched the frozen binary with
    `os.environ | {...}` — it was green on the same Windows build where this
    was red, which is precisely how the divergence survived.
    """
    return {**os.environ, **extra}


def handshake(server: dict, *, timeout: float = 30.0) -> dict:
    """Run the advertised command and complete an MCP `initialize` with it.

    The reader's real question after Connect is not "was the file written" — it
    is "does it work", and the two are different failures with different fixes.
    A config can be written perfectly into a harness that then cannot start the
    process at all, and until the agent silently returns nothing there is no
    sign of it.

    So this runs exactly what the config names, in a plain environment, and
    reports the first JSON line it gets back. It is a *diagnostic*, not a
    terminal: the command is the one the app just advertised, never one the
    caller supplies. A local server that will run whatever it is handed is a
    remote-code-execution hole reachable by anything that can reach the port —
    including the browser extension's socket.
    """
    import json
    import subprocess
    import time

    request = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "kriko-app", "version": "0"},
        },
    }) + "\n"

    try:
        process = subprocess.Popen(
            [server["command"], *server.get("args", [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            env=_launch_environment(server.get("env", {})),
        )
    except OSError as exc:
        return {"ok": False, "detail": f"could not start the command: {exc}"}

    try:
        process.stdin.write(request)
        process.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            try:
                answer = json.loads(line)
            except ValueError:
                continue  # a server that logs to stdout is noisy, not broken
            name = (answer.get("result") or {}).get("serverInfo", {}).get("name")
            if name:
                return {"ok": True, "server": name}
            return {"ok": False, "detail": f"answered, but not as an MCP server: {line[:200]}"}
        # stderr is the whole diagnosis when a command fails to start properly —
        # a missing module, a venv that moved — and it is never seen otherwise.
        process.kill()
        return {"ok": False, "detail": (process.stderr.read() or "no answer").strip()[:2000]}
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    finally:
        if process.poll() is None:
            process.kill()
