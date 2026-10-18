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
from app import agentconfig, agentskill, prefs
from app.web import state
from app.web.deps import get_app_state, get_store

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
    # Carried explicitly rather than assumed inherited — see
    # `agentconfig.platform_env`'s docstring for why a harness's own merge
    # behaviour is not something this config can safely depend on.
    if getattr(sys, "frozen", False):
        return {
            "command": str(Path(sys.executable).resolve()),
            "args": ["--mcp", *store],
            "env": agentconfig.platform_env(),
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
        "env": {**agentconfig.platform_env(), "PYTHONPATH": str(src)},
        "frozen": False,
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
        body = skill_body(settings, store)
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


def _kind(row: dict) -> str:
    """What an agent row *is*, from the engine's own flags.

    `local` and `cost_basis` are how `prefs` already tells the three apart: the
    row for the model on this machine carries `local`, an agent billed per
    token carries `per_token`, and a coding-agent CLI carries neither. The
    screen owns the reader's words for these; this is the fact under them.
    """
    if row.get("local"):
        return "local"
    return "api" if row.get("cost_basis") == "per_token" else "cli"


def _market_action(state: str, *, wiring: dict | None, runnable: bool,
                   installable: bool) -> str:
    """The one thing to press, from the state the engine found.

    `use` only where Kriko itself runs the agent, which is the choice the
    reader is making between two rows. Writing a harness config is Connect's
    business, so an agent that answers somewhere else — an app, an editor —
    still offers Connect and never Use, however connected its config is. A
    harness with no config Kriko can write, and no install of its own, has
    nothing to press but the reason it is not ready.
    """
    if state == "not_installed":
        return "install" if installable else "setup"
    if not runnable:
        return "connect" if wiring is not None else "setup"
    if state == "ready":
        return "use" if wiring is None or wiring["state"] == "connected" else "connect"
    return "connect" if wiring is not None else "setup"


def _market_row(row: dict, state: str, *, runnable: bool, wiring: dict | None,
                chosen: bool) -> dict:
    """One agent as the marketplace lists it: what it is, whether this machine
    can run it now, how that was found, and the one action left to take."""
    return {
        "id": row["id"],
        "label": row["label"],
        "kind": _kind(row),
        "state": state,
        # The engine's own sentence for why it is not ready, or what a run with
        # it bills. Empty where the engine said nothing, rather than a line
        # written here that would drift from what it knows.
        "detail": (wiring or {}).get("detail") or row.get("why")
        or row.get("install_hint") or row.get("needs_account") or "",
        # How this installation knows: the binary it located, the model
        # server's address, or the command it looked for and did not find.
        "where": row.get("path") or row.get("command") or (wiring or {}).get("path") or "",
        "wiring": (wiring or {}).get("state", ""),
        "action": _market_action(
            state,
            wiring=wiring,
            runnable=runnable,
            installable=bool(row.get("can_install")),
        ),
        "can_install": bool(row.get("can_install")),
        "url": row.get("download_url") or "",
        "chosen": chosen,
        "local": bool(row.get("local")),
    }


@router.get("/agent-market")
def agent_market(request: Request, conn=Depends(get_app_state)) -> dict:
    """Every way of answering a question this install can run, one row each.

    A market is not a second discovery. `prefs.choices` already finds the CLIs
    on this machine, the model server and the saved keys, so this asks it once
    and adds only what a *market* needs and a preference screen does not:
    which kind of thing each row is, and whether this window's store has been
    written into its config (`agentconfig.status_of`). The ids are the same
    ones `/api/prefs` uses, so the model dials and the reader's own arrangement
    stay joined to these rows.
    """
    settings = request.app.state.settings
    choices = prefs.choices(conn)
    api_ready, api_missing = prefs.api_agent_rows(conn)
    wiring = {
        target.id: agentconfig.status_of(
            target, server_name=SERVER_NAME, store_path=Path(settings.store_path)
        )
        for target in agentconfig.targets()
    }
    chosen = str(choices["chosen"].get(prefs.HARNESS) or "")
    groups = [
        ((row, "ready", True) for row in choices["harnesses"]),
        ((row, "ready", True) for row in api_ready),
        # A harness config Kriko can write is a row even where the CLI behind
        # it cannot run a check here: connecting it is how that agent reaches
        # this store, and it is the only action the row has.
        ((
            {"id": target.id, "label": target.label},
            "ready" if wiring[target.id]["state"] == "connected" else "needs_setup",
            False,
        ) for target in agentconfig.targets()),
        ((row, "needs_setup", False) for row in choices["unusable"]),
        ((row, "not_installed", False) for row in choices["missing"]),
        ((row, "not_installed", False) for row in api_missing),
    ]
    agents: list[dict] = []
    for group in groups:
        for row, standing, runnable in group:
            if any(one["id"] == row["id"] for one in agents):
                continue
            agents.append(_market_row(
                row, standing,
                runnable=runnable,
                wiring=wiring.get(row["id"]),
                chosen=row["id"] == chosen,
            ))
    return {"agents": agents, "chosen": chosen}


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
    body = skill_body(request.app.state.settings, store)
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


def skill_body(settings, store) -> str:
    """The skill as this window renders it, for every reader of that word.

    One function because there used to be four call sites and two answers:
    startup rendered without the agenda snapshot, while the status check and the
    Update button rendered with it. What the digest hashes no longer depends on
    the snapshot (`agentskill.snapshot`), but what gets *written* should not
    depend on the door either, so nothing renders the skill for this app except
    here (B157).
    """
    return agentskill.render(store, _agenda_rows(settings, store)) or ""


def _agenda_rows(settings, store) -> list[dict]:
    """The agenda, or nothing, for the skill's snapshot.

    Best-effort on purpose: the skill is the protocol and the snapshot is a
    convenience on top of it, so a log that cannot be read or a missing
    `app.sqlite` must cost the reader a head start and never the document.
    """
    try:
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
    body = skill_body(request.app.state.settings, store)
    return {
        "name": agentskill.SKILL_NAME,
        "steps": [
            {"tool": tool, "input": given, "output": got}
            for tool, given, got in agentskill.STEPS
        ],
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
    body = skill_body(settings, store)
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
