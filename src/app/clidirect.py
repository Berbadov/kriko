"""Read the app's own state straight from its files, for the CLI's read commands.

The HTTP-backed subcommands (`prefs`, `costs`, `sites list`, `verify --list`,
`drafts list/show`, `operations`) used to attach to a running engine or start
one of their own — a whole FastAPI server spawned to answer "what did I
spend", and an answer that differed depending on whether some other engine
happened to be running. The read-only half of those commands never needed the
server: every answer is computed by the same modules the routers call, over
`app.sqlite` and, for sites and drafts, the store and the drafts directory.
This module is that path: one connection, no server, no spawn, so the CLI
answers within a single short process and always from the files beside
`--store` — the same ones the desktop app reads.

The connection is opened read-only when SQLite allows it (`mode=ro`), and
otherwise with `PRAGMA query_only`: a read-only URI cannot open a WAL database
whose shared-memory file it may not create, and the app keeps `app.sqlite` in
WAL. `query_only` still lets SQLite attach to the existing `-shm` while
refusing every write on this connection, which is the actual guarantee — a
reader CLI must never migrate or checkpoint the reader's history. A missing
file is not an error: a machine that never ran the app simply has no state,
and the callers answer with the empty payload.
"""

import sqlite3
from pathlib import Path


def app_state_path(store_arg: str | None) -> Path:
    """The `app.sqlite` beside the store this command opened.

    The same derivation `app.cli._siblings` and `app.mcp_server` make, so
    `--store` pointed at a copy reads that copy's state and never the
    reader's real one.
    """
    from kriko.store.db import DEFAULT_STORE

    store_path = Path(store_arg) if store_arg else DEFAULT_STORE
    return store_path.parent / "app.sqlite"


def store_path(store_arg: str | None) -> Path:
    from kriko.store.db import DEFAULT_STORE

    return Path(store_arg) if store_arg else DEFAULT_STORE


def open_readonly(path: Path) -> sqlite3.Connection | None:
    """A connection that cannot write, or `None` when there is no file yet."""
    path = Path(path)
    if not path.exists():
        return None
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.OperationalError:
        # A WAL database whose -shm/-wal this process may not create (or may
        # not see) refuses `mode=ro`; fall back to a normal open fenced by
        # `query_only`, which still writes nothing.
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def scratch() -> sqlite3.Connection:
    """An empty in-memory app state.

    For a read command on a machine where the app has never run: there is no
    `app.sqlite` to open, and the answer is the empty one — but the shared
    readers (`costs.overview`, `state.operations`, …) still expect the tables
    to exist, so the schema is applied to memory instead of inventing a second
    empty shape that would drift from the real one.
    """
    from app.web import state

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(state.SCHEMA)
    return conn


def operations(conn: sqlite3.Connection, limit: int = 50, after_id: int = 0) -> dict:
    """The live feed, minus the HTTP-only clock: same rows the router serves."""
    from app.web import state

    items = state.operations(conn, limit=limit, after_id=after_id)
    return {
        "items": items,
        "running": state.running_operations(conn),
        "last_id": max(
            (one["op_id"] for one in items if one["op_id"] > after_id),
            default=after_id,
        ),
    }


def costs(conn: sqlite3.Connection) -> dict:
    from app import costs as costs_mod

    return costs_mod.overview(conn)


def sites(store, conn: sqlite3.Connection) -> dict:
    from app import sites as sites_mod

    registered = [dict(row) for row in sites_mod.registered(store, conn)]
    for row in registered:
        row["activation"] = sites_mod.activation(store, conn, row["site"])
    return {
        "registered": registered,
        "requested": sites_mod.requested(store, conn),
    }


def fact_checks(conn: sqlite3.Connection, verdict: str = "", limit: int = 200) -> dict:
    from app.web import state

    return {
        "items": state.fact_checks(conn, verdict=verdict or None, limit=limit),
        "counts": state.fact_check_counts(conn),
    }


def drafts(store_arg: str | None) -> dict:
    from app import packdraft

    return {"items": packdraft.listing(store_path(store_arg))}


def draft(store_arg: str | None, slug: str) -> dict:
    from app import packauthor, packdraft

    try:
        return packauthor.draft_state(store_path(store_arg), slug)
    except packdraft.DraftRefused:
        raise KeyError(f"no draft {slug!r}") from None


def prefs(conn: sqlite3.Connection, app_state: Path, fresh: bool = False) -> dict:
    from app import prefs as prefs_mod

    return prefs_mod.choices(conn, app_state_path=app_state, fresh=fresh)
