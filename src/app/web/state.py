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
