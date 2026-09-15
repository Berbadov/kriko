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

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app import agenda as agenda_mod
from app import agentconfig, agentskill
from app.web import state
from app.web.deps import get_store

log = logging.getLogger(__name__)

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
    server = _server_block(settings)
    return {
        "server_name": SERVER_NAME,
        "frozen": entry["frozen"],
        "store": str(settings.store_path),
        "mcp_json": {"mcpServers": {SERVER_NAME: server}},
        # Named so the UI does not have to know the tool list to explain the
        # protocol: these are the two an agent cannot work without.
        "tools": ["research_brief", "coverage_gaps", "submit_findings"],
    }


def _server_block(settings) -> dict:
    entry = command_for(Path(settings.store_path))
    server = {"type": "stdio", "command": entry["command"], "args": entry["args"]}
    if entry["env"]:
        server["env"] = entry["env"]
    return server


@router.get("/agent-targets")
def agent_targets(request: Request):
    """Which harnesses are on this machine, and whether each one is wired.

    The copy-block above is still the honest fallback for a harness nobody has
    taught us about; this exists because for the four we do know, "find this
    file, understand its schema, merge one key without breaking the rest" is
    work the app can simply do.
    """
    settings = request.app.state.settings
    # Rendered once for the whole list: the skill is the same document for
    # every harness, and rendering it per row would read every pack four times
    # to answer one question.
    from kriko.store.db import connect

    store = connect(settings.store_path)
    try:
        body = agentskill.render(store, _agenda_rows(request, store)) or ""
    except Exception:  # noqa: BLE001 — a skill that will not render must not
        # take the screen that would have told the reader why.
        body = ""
    finally:
        store.close()
    return {
        "server_name": SERVER_NAME,
        "store": str(settings.store_path),
        "targets": [
            {
                **agentconfig.status_of(
                    target,
                    server_name=SERVER_NAME,
                    store_path=Path(settings.store_path),
                ),
                # Whether the *protocol* on disk is the current one, which is a
                # different question from whether the harness is wired — and
                # the one nobody could ask before.
                "skill": agentconfig.skill_status(
                    target, agentskill.SKILL_NAME, body
                ),
            }
            for target in agentconfig.targets()
        ],
    }


@router.post("/agent-targets/{target_id}/skill")
def refresh_target_skill(target_id: str, request: Request, store=Depends(get_store)):
    """Rewrite one harness's skill from what is installed right now.

    Separate from Connect because they are separate decisions: Connect points a
    harness at this store, and this updates the protocol it was given. A reader
    whose pack updated yesterday wants the second without redoing the first.
    """
    target = agentconfig.by_id(target_id)
    if target is None:
        raise HTTPException(404, f"unknown harness: {target_id}")
    body = agentskill.render(store, _agenda_rows(request, store)) or ""
    if not body:
        raise HTTPException(409, "there is no skill to write yet")
    try:
        written = agentconfig.write_skill(target, agentskill.SKILL_NAME, body)
    except OSError as exc:
        raise HTTPException(500, f"could not write the skill: {exc}") from exc
    return {
        "target": target_id,
        "skill": written,
        "status": agentconfig.skill_status(target, agentskill.SKILL_NAME, body),
    }


def _agenda_rows(request: Request, store) -> list[dict]:
    """The agenda, or nothing, for the skill's snapshot.

    Best-effort on purpose: the skill is the protocol and the snapshot is a
    convenience on top of it, so a log that cannot be read or a missing
    `app.sqlite` must cost the reader a head start and never the document.
    """
    try:
        settings = request.app.state.settings
        app_state = state.connect(settings.app_state_path)
        try:
            return agenda_mod.compute(
                store,
                app_state=app_state,
                log_path=settings.analysis_log_path,
                limit=5,
            )["rows"]
        finally:
            app_state.close()
    except Exception:
        log.warning("could not compute the agenda for the skill", exc_info=True)
        return []


@router.get("/agent-skill")
def agent_skill(request: Request, store=Depends(get_store)):
    """The protocol, assembled from the packs that are installed right now.

    Served as well as written so a reader on an unsupported harness can still
    read it, and so the UI can show what Connect is about to put on disk.
    """
    body = agentskill.render(store, _agenda_rows(request, store))
    return {
        "name": agentskill.SKILL_NAME,
        "steps": [{"tool": tool, "why": why} for tool, why in agentskill.STEPS],
        # Always a body now. An empty installation gets the authoring half of
        # the skill rather than nothing: the job for an agent connected to a
        # store with no packs is to write the first one (B96).
        "body": body,
    }


@router.post("/agent-targets/{target_id}/connect")
def connect_target(target_id: str, request: Request, store=Depends(get_store)):
    """Write this installation's address into one harness's config.

    A 409 rather than a 500 when the config will not parse: the reader broke
    it, the fix is theirs, and the message names the file so they can make it.
    """
    target = agentconfig.by_id(target_id)
    if target is None:
        raise HTTPException(404, f"unknown harness: {target_id}")
    settings = request.app.state.settings
    try:
        agentconfig.connect(
            target, server_name=SERVER_NAME, server=_server_block(settings)
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"could not write {target.path}: {exc}") from exc
    # Best-effort, and after the config: the connection is the thing the reader
    # asked for, and a harness with nowhere to put a skill still gets one.
    skill_written = None
    body = agentskill.render(store, _agenda_rows(request, store))
    if body:
        try:
            skill_written = agentconfig.write_skill(target, agentskill.SKILL_NAME, body)
        except OSError:
            skill_written = None
    row = agentconfig.status_of(
        target, server_name=SERVER_NAME, store_path=Path(settings.store_path)
    )
    return {**row, "skill": skill_written}


@router.post("/agent-verify")
def agent_verify(request: Request):
    """Start the advertised command and see whether it answers.

    Deliberately not an endpoint that runs a command the caller names. This
    process listens on a local port that a browser extension also talks to; a
    "run this for me" route there is a remote-code-execution hole with a nice
    name. The only command this will ever start is the one it just told the
    reader to configure.
    """
    return agentconfig.handshake(_server_block(request.app.state.settings))
