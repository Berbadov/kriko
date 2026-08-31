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
    conn.commit()
    return cursor.rowcount > 0
