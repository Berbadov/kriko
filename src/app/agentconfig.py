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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SERVER_KEY = "mcpServers"

#: Windows will not start *any* process without `SystemRoot` — it is how the
#: loader finds its own DLLs — and a frozen PyInstaller onefile additionally
#: needs `TEMP`/`TMP` to unpack itself before `--mcp` is ever parsed. Losing
#: either is not a warning, it is the process dying before line one of our
#: code runs, with nothing on stdout for a stdio JSON-RPC client to frame and
#: only stderr (which nothing reads once written) saying why. Whether the
#: harness that spawns our advertised command merges its own environment with
#: the `env` block we hand it, or replaces it outright, is exactly the
#: uncertainty B131 was filed on — so these are carried explicitly in every
#: config this module writes, never left to that assumption either way.
#: `USERPROFILE` (with `HOMEDRIVE`/`HOMEPATH` behind it, which is how Windows
#: answers `~` when the first is unset) joined the list once a harness that
#: replaces the environment was actually tried: the store resolves
#: `Path.home() / ".kriko"` at import, so without it the sidecar raises
#: `RuntimeError: Could not determine home directory` on the way up — the same
#: "cannot connect to the server: kriko" the keys above were added for, one
#: variable further in and equally invisible to the reader.
_WINDOWS_ENV_KEYS = (
    "SystemRoot", "TEMP", "TMP", "ComSpec", "PATH",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
)


def platform_env(
    platform: str | None = None, environ: Mapping[str, str] | None = None
) -> dict:
    """The variables a Windows child cannot start without, or `{}` elsewhere.

    Takes `platform`/`environ` rather than reading `sys.platform`/`os.environ`
    directly so a test can prove the Windows branch without running on
    Windows — the failure this exists for cannot otherwise be reproduced in
    this repository's CI at all.
    """
    platform = platform if platform is not None else sys.platform
    if platform != "win32":
        return {}
    environ = environ if environ is not None else os.environ
    return {key: environ[key] for key in _WINDOWS_ENV_KEYS if environ.get(key)}


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


def _appdata() -> Path | None:
    """Windows' roaming app-data root — the module's *second* home.

    A function rather than an `os.environ` read at the call site, and named
    alongside `_home` on purpose. Everything this module writes goes under one
    of these two roots, and until now only one of them could be redirected: the
    one-click tests pointed `_home` at a tmp directory and believed that meant
    no test could touch the author's real configs, while Claude Desktop's path
    went straight to the live `%APPDATA%` underneath them. On Windows that made
    the promise false for one target out of four — the one whose config a test
    could therefore overwrite.

    Falls back to the conventional location when the variable is unset, which
    is also what makes redirecting `_home` alone enough on a machine that has
    no `%APPDATA%` at all.

    But an unset `%APPDATA%` was never the only way this leaked: on a real
    Windows machine it is always set, so a caller who redirects `HOME`/
    `USERPROFILE` alone — every one-click test, `tools/walk.sh`'s isolated
    runs — still got the *real* `%APPDATA%` back here, because the inherited
    environment variable was trusted over the redirected home. That made the
    isolation the docstring above claims true for three targets out of four
    and silently false for Claude Desktop, whose config a redirected run could
    still read (or, worse, overwrite). So `%APPDATA%` is honoured only when it
    is actually consistent with `_home()` — the ordinary case on a real
    install, where the two always agree — and a `HOME` redirected out from
    under it falls back to the home-relative path instead of the inherited
    real one.
    """
    home = _home()
    base = os.environ.get("APPDATA")
    if base:
        base_path = Path(base)
        try:
            base_path.resolve().relative_to(home.resolve())
            return base_path
        except ValueError:
            pass
    return home / "AppData" / "Roaming"


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
        base = _appdata()
        return base / "Claude/claude_desktop_config.json" if base else None
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
    assert target.path is not None
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


def skill_status(target: Target, name: str, body: str) -> dict:
    """Whether this harness has the *current* skill on disk.

    Three answers, and they are three different situations: `unsupported` (this
    harness has nowhere to put a skill), `missing` (it has somewhere and there
    is nothing there), `stale` (there is something there and it is not what
    this build would write).

    Stale is the one that matters and the one nothing could see before. The
    skill is generated from the installed packs and from this app's own code,
    and it was written exactly once — when the reader pressed Connect. So an
    overhauled protocol, a tool that did not exist last month, or a pack that
    updated yesterday all reached the code and never reached the agent, and
    from the reader's side the answer to "did the skill change" was correctly
    *no*.

    "Current" compares the protocol only. The agenda snapshot and the pack
    counts are fenced out of the digest (`agentskill.snapshot`), because they
    change with every analysis and read as stale again straight after the
    button cleared them (B157).
    """
    path = skill_path(target, name)
    if path is None:
        return {"supported": False, "path": None, "present": False, "stale": False}
    from app import agentskill

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    present = bool(text.strip())
    return {
        "supported": True,
        "path": str(path),
        "present": present,
        "stale": present and agentskill.digest_of_file(text) != agentskill.digest(body),
    }


def refresh_skills(name: str, body: str) -> list[dict]:
    """Rewrite the skill wherever a stale or missing copy is already wired.

    Called at startup. Only for harnesses this installation is *already*
    connected to: writing into the config directory of a CLI the reader never
    wired would be installing something they did not ask for, and the check
    for "already wired" is the file being there, not a preference somewhere.

    Silent per target, because a read-only home directory or a CLI that moved
    is not a reason the app fails to start — it is a row on the Agents screen
    saying the copy on disk is old.
    """
    written: list[dict] = []
    if not body:
        return written
    for target in targets():
        status = skill_status(target, name, body)
        if not status["supported"] or not status["present"]:
            # Nothing there is not staleness: a harness the reader never
            # connected gets nothing until they press Connect.
            continue
        if not status["stale"]:
            continue
        try:
            path = write_skill(target, name, body)
        except OSError:
            continue
        if path:
            written.append({"target": target.id, "path": path})
    return written


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

    So this runs exactly what the config names, in a plain environment,
    completes `initialize`, and — because a server that answers `initialize`
    but exposes nothing is exactly as useless to the reader — asks it to
    `tools/list` too, on the same connection. It is a *diagnostic*, not a
    terminal: the command is the one the app just advertised, never one the
    caller supplies. A local server that will run whatever it is handed is a
    remote-code-execution hole reachable by anything that can reach the port —
    including the browser extension's socket.
    """
    import json
    import subprocess
    import time

    def frame(method: str, params: dict, id_: int | None) -> str:
        message: dict = {"jsonrpc": "2.0", "method": method, "params": params}
        if id_ is not None:
            message["id"] = id_
        return json.dumps(message) + "\n"

    def read_reply(deadline: float) -> dict | None:
        """The next line that parses as JSON, or `None` if the deadline or
        the process passes first. A server that logs to stdout is noisy, not
        broken, so a line that is not JSON is skipped rather than failed on."""
        assert process.stdout is not None
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                return None
            try:
                return json.loads(line)
            except ValueError:
                continue
        return None

    try:
        process = subprocess.Popen(
            [server["command"], *server.get("args", [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            env=_launch_environment(server.get("env", {})),
        )
    except OSError as exc:
        return {"ok": False, "detail": f"could not start the command: {exc}"}
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    try:
        deadline = time.time() + timeout
        process.stdin.write(frame(
            "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kriko-app", "version": "0"},
            }, 1,
        ))
        process.stdin.flush()
        answer = read_reply(deadline)
        if answer is None:
            process.kill()
            return {"ok": False, "detail": (process.stderr.read() or "no answer").strip()[:2000]}
        name = (answer.get("result") or {}).get("serverInfo", {}).get("name")
        if not name:
            return {"ok": False, "detail": f"answered, but not as an MCP server: {json.dumps(answer)[:200]}"}

        # The lifecycle notification a well-behaved client always sends, and
        # the one point where this diagnostic must not itself be the reason
        # the check fails: a server that (correctly, per this SDK's own
        # `ServerSession`) does not require it before answering `tools/list`
        # must not be marked broken because *our* write failed to reach a
        # process that had already exited cleanly for some other reason.
        try:
            process.stdin.write(frame("notifications/initialized", {}, None))
            process.stdin.flush()
        except (OSError, ValueError):
            pass

        process.stdin.write(frame("tools/list", {}, 2))
        process.stdin.flush()
        listed = read_reply(deadline)
        if listed is None:
            process.kill()
            return {
                "ok": False,
                "detail": "initialized, but tools/list got no answer: "
                + (process.stderr.read() or "(no stderr)").strip()[:2000],
            }
        tools = [t.get("name") for t in (listed.get("result") or {}).get("tools", [])]
        if not tools:
            return {
                "ok": False,
                "detail": f"initialized, but tools/list named none: {json.dumps(listed)[:200]}",
            }
        return {"ok": True, "server": name, "tools": tools}
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    finally:
        if process.poll() is None:
            process.kill()
