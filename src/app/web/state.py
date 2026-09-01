"""UI state: lookup history and interface settings.

This is `app/`'s own SQLite file, `~/.kriko/app.sqlite`, deliberately separate
from the engine's `knowledge.sqlite`. The engine's schema is its contract with
pack authors — every table in it is something a pack writes or a ranker reads.
A `lookups` table there would be the first one nobody in `kriko/` uses, and the
precedent that admits the next one.

Two consequences settle it: uninstalling a pack must not drop your history, and
a history row must never affect a pack's `content_digest`.
"""

import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS lookups (
    lookup_id     TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    source        TEXT NOT NULL,
    label         TEXT NOT NULL,
    request_json  TEXT NOT NULL,
    response_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lookups_created_at ON lookups (created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Triage: which claims of a stored answer the reader has dealt with.
-- Keyed by (lookup_id, claim_key) rather than by claim_id, because an
-- /api/analyze payload has no claim_id and the reader's checkmark must
-- survive anyway. The key is whatever the UI can compute from a claim it
-- has in hand; the engine never sees it.
-- Long work, as rows first and a stream second. A job that exists only in a
-- thread cannot be recovered after a restart, and "a spinner that never
-- resolves" is the failure mode this table exists to make impossible.
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    params_json      TEXT NOT NULL,
    state            TEXT NOT NULL,
    progress         REAL NOT NULL DEFAULT 0,
    message          TEXT NOT NULL DEFAULT '',
    log              TEXT NOT NULL DEFAULT '',
    result_json      TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs (created_at DESC);

CREATE TABLE IF NOT EXISTS claim_checks (
    lookup_id  TEXT NOT NULL,
    claim_key  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (lookup_id, claim_key)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def record_lookup(
    conn: sqlite3.Connection,
    *,
    source: str,
    label: str,
    request: dict,
    response: dict,
) -> str:
    lookup_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO lookups"
        " (lookup_id, created_at, source, label, request_json, response_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            lookup_id,
            datetime.now(UTC).isoformat(timespec="seconds"),
            source,
            label,
            json.dumps(request, default=str),
            json.dumps(response, default=str),
        ),
    )
    conn.commit()
    return lookup_id


def _decode(row: sqlite3.Row) -> dict:
    return {
        "lookup_id": row["lookup_id"],
        "created_at": row["created_at"],
        "source": row["source"],
        "label": row["label"],
        "request": json.loads(row["request_json"]),
        "response": json.loads(row["response_json"]),
    }


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Newest first.

    `created_at` has second resolution, so two lookups a moment apart tie on
    it; `rowid DESC` breaks the tie by insertion order rather than leaving it
    to SQLite. `claim_count` is computed here so a list view does not have to
    parse every stored response just to show a number.
    """
    rows = conn.execute(
        "SELECT lookup_id, created_at, source, label, response_json FROM lookups"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (max(0, limit),),
    ).fetchall()
    out = []
    for row in rows:
        response = json.loads(row["response_json"])
        out.append(
            {
                "lookup_id": row["lookup_id"],
                "created_at": row["created_at"],
                "source": row["source"],
                "label": row["label"],
                "claim_count": len(response.get("claims") or []),
            }
        )
    return out


def get_lookup(conn: sqlite3.Connection, lookup_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM lookups WHERE lookup_id = ?", (lookup_id,)
    ).fetchone()
    return _decode(row) if row else None


def delete_lookup(conn: sqlite3.Connection, lookup_id: str) -> bool:
    cursor = conn.execute("DELETE FROM lookups WHERE lookup_id = ?", (lookup_id,))
    # Forgetting an answer forgets the triage on it too. Leaving the checks
    # behind would let a new lookup that happened to reuse the id inherit
    # someone else's checkmarks.
    conn.execute("DELETE FROM claim_checks WHERE lookup_id = ?", (lookup_id,))
    conn.commit()
    return cursor.rowcount > 0


# ── interface settings ───────────────────────────────────────────────────
#
# Deliberately a key/value table with JSON values rather than typed columns.
# Every row here is a UI preference — mode, a remembered pack — and none of
# them is worth a migration when the UI grows a fourth one.


def all_settings(conn: sqlite3.Connection) -> dict:
    return {
        row["key"]: json.loads(row["value"])
        for row in conn.execute("SELECT key, value FROM settings")
    }


def put_settings(conn: sqlite3.Connection, values: dict) -> dict:
    """Merge, never replace: a caller saving one preference must not clear
    the others just because it did not know about them."""
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(key, json.dumps(value)) for key, value in values.items()],
    )
    conn.commit()
    return all_settings(conn)


# ── triage ───────────────────────────────────────────────────────────────


def checked_keys(conn: sqlite3.Connection, lookup_id: str) -> list[str]:
    return [
        row["claim_key"]
        for row in conn.execute(
            "SELECT claim_key FROM claim_checks WHERE lookup_id = ?"
            " ORDER BY claim_key",
            (lookup_id,),
        )
    ]


def set_checked(
    conn: sqlite3.Connection, lookup_id: str, claim_key: str, checked: bool
) -> list[str]:
    if checked:
        conn.execute(
            "INSERT OR IGNORE INTO claim_checks (lookup_id, claim_key, created_at)"
            " VALUES (?, ?, ?)",
            (lookup_id, claim_key, datetime.now(UTC).isoformat(timespec="seconds")),
        )
    else:
        conn.execute(
            "DELETE FROM claim_checks WHERE lookup_id = ? AND claim_key = ?",
            (lookup_id, claim_key),
        )
    conn.commit()
    return checked_keys(conn, lookup_id)


# ── jobs ─────────────────────────────────────────────────────────────────
#
# `queued -> running -> (succeeded | failed | cancelled | interrupted)`.
# `interrupted` is not an error state a handler can produce: it is what a row
# left `running` by a killed process becomes at the next startup, so a lost job
# is visible as a state rather than as a spinner nobody can explain.

QUEUED, RUNNING = "queued", "running"
SUCCEEDED, FAILED, CANCELLED, INTERRUPTED = (
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
)
TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED, INTERRUPTED})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create_job(conn: sqlite3.Connection, kind: str, params: dict) -> str:
    job_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO jobs (job_id, kind, params_json, state, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (job_id, kind, json.dumps(params, default=str), QUEUED, _now()),
    )
    conn.commit()
    return job_id


def start_job(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute(
        "UPDATE jobs SET state = ?, started_at = ? WHERE job_id = ?",
        (RUNNING, _now(), job_id),
    )
    conn.commit()


def update_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    progress: float | None = None,
    message: str | None = None,
    line: str | None = None,
) -> None:
    """Progress, a headline, and an appended log line — any subset.

    The log is appended in SQL rather than read-modify-written in Python so a
    reader polling the row cannot see a line vanish between two writes.
    """
    sets, args = [], []
    if progress is not None:
        sets.append("progress = ?")
        args.append(max(0.0, min(1.0, progress)))
    if message is not None:
        sets.append("message = ?")
        args.append(message)
    if line is not None:
        sets.append("log = log || ?")
        args.append(f"{line}\n")
    if not sets:
        return
    args.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ?", args)
    conn.commit()


def finish_job(
    conn: sqlite3.Connection,
    job_id: str,
    state: str,
    *,
    result: dict | None = None,
    message: str = "",
) -> None:
    conn.execute(
        "UPDATE jobs SET state = ?, finished_at = ?, progress = ?,"
        "       message = COALESCE(NULLIF(?, ''), message), result_json = ?"
        " WHERE job_id = ?",
        (
            state,
            _now(),
            1.0 if state == SUCCEEDED else 0.0,
            message,
            json.dumps(result, default=str) if result is not None else None,
            job_id,
        ),
    )
    conn.commit()


def request_cancel(conn: sqlite3.Connection, job_id: str) -> str | None:
    """Ask a job to stop, and report the state it is in.

    A queued job is cancelled outright — nothing has happened yet. A running
    one is only *asked*: the flag is a row the handler reads between steps,
    because killing a thread mid-write is how a half-installed pack happens.
    """
    row = get_job(conn, job_id)
    if row is None:
        return None
    if row["state"] == QUEUED:
        finish_job(conn, job_id, CANCELLED, message="cancelled before it started")
        return CANCELLED
    if row["state"] == RUNNING:
        conn.execute(
            "UPDATE jobs SET cancel_requested = 1, message = ? WHERE job_id = ?",
            ("cancelling…", job_id),
        )
        conn.commit()
        return RUNNING
    return row["state"]


def cancel_requested(conn: sqlite3.Connection, job_id: str) -> bool:
    row = conn.execute(
        "SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    return bool(row and row["cancel_requested"])


def _job(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["params"] = json.loads(out.pop("params_json") or "{}")
    result = out.pop("result_json")
    out["result"] = json.loads(result) if result else None
    out["cancel_requested"] = bool(out["cancel_requested"])
    out["done"] = out["state"] in TERMINAL
    return out


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _job(row) if row else None


def list_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (max(0, limit),),
    ).fetchall()
    return [_job(row) for row in rows]


def interrupt_running(conn: sqlite3.Connection) -> int:
    """Called at startup. Anything still `running` belongs to a dead process."""
    cursor = conn.execute(
        "UPDATE jobs SET state = ?, finished_at = ?, message = ?"
        " WHERE state IN (?, ?)",
        (
            INTERRUPTED,
            _now(),
            "the server stopped while this was running",
            RUNNING,
            QUEUED,
        ),
    )
    conn.commit()
    return cursor.rowcount
