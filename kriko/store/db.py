"""SQLite connection handling for pack files and the installed store.

One schema serves both (see `schema.sql`), so this module makes no distinction
between them — `connect()` opens either.

No ORM. The old serving plane used SQLAlchemy against Postgres; that bought
dialect portability we no longer want, since the pack format *is* SQLite and a
pack file is meant to be openable by anything that speaks it.
"""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_VERSION = 1

# Default location of the reader's installed store. The authoring ledger lives
# beside it as `ledger.sqlite` and is deliberately a separate file: it is
# append-only with DELETE/UPDATE triggers, while this store must support
# `DELETE WHERE pack_id = ?`. Those two facts cannot share a database.
DEFAULT_HOME = Path.home() / ".kriko"
DEFAULT_STORE = DEFAULT_HOME / "knowledge.sqlite"


def connect(path=None, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a store or pack file, applying the schema if it is new.

    WAL is set from the first connection because the web app reads while
    pipeline subprocesses write to the same file. Under the default rollback
    journal that is an `SQLITE_BUSY` waiting to happen; today's code only avoids
    it by using two separate database files.
    """
    path = Path(path) if path is not None else DEFAULT_STORE
    path.parent.mkdir(parents=True, exist_ok=True)

    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    return conn


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
