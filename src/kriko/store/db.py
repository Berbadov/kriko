"""SQLite connection handling for pack files and the installed store.

One schema serves both (see `schema.sql`), so this module makes no distinction
between them — `connect()` opens either.

No ORM: the pack format *is* SQLite, and a pack file is meant to be openable
by anything that speaks it, so dialect portability is not a goal here.
"""

import sqlite3
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_VERSION = 1

# Default location of the reader's installed store. The authoring ledger lives
# beside it as `ledger.sqlite` and is deliberately a separate file: it is
# append-only with DELETE/UPDATE triggers, while this store must support
# `DELETE WHERE pack_id = ?`. Those two facts cannot share a database.
DEFAULT_HOME = Path.home() / ".kriko"
DEFAULT_STORE = DEFAULT_HOME / "knowledge.sqlite"

# DEFAULT_STORE's filename has changed before this branch's own history: an
# earlier default briefly shipped under a different name. Renaming a default
# path silently starts a second store and orphans whatever the old default
# already wrote — and there is no way for this module to know, in general,
# what an old default used to be called. So the guard below does not name
# one specific old filename; it looks for *any other* store-shaped file
# sitting where the default is about to be created, and warns once rather
# than guessing which one the owner considers current.
_warned_other_store_present = False


def _warn_if_other_store_present(path: Path) -> None:
    """Warn once if another `*.sqlite` file already sits beside the default.

    Only fires for the *default* location — an explicit `path=` is the
    caller's own choice and not this module's business to second-guess.
    Never moves, deletes, or reads the other file; naming both paths is the
    entire job.
    """
    global _warned_other_store_present
    if _warned_other_store_present or not path.parent.is_dir():
        return
    others = sorted(
        p for p in sorted(path.parent.glob("*.sqlite"))
        if p != path and p.is_file()
    )
    if not others:
        return
    _warned_other_store_present = True
    other_list = ", ".join(str(p) for p in others)
    print(
        f"kriko: using {path} as the default store.\n"
        f"kriko: also found {other_list} in the same directory — it is not "
        f"being read or written. If it holds data you expect to see, point "
        f"KRIKO_STORE at it (or migrate it into {path} yourself); kriko "
        f"will not move, delete, or merge it automatically.",
        file=sys.stderr,
    )


def connect(path=None, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a store or pack file, applying the schema if it is new.

    WAL is set from the first connection because the web app reads while
    pipeline subprocesses write to the same file. Under the default rollback
    journal that is an `SQLITE_BUSY` waiting to happen; today's code only avoids
    it by using two separate database files.
    """
    used_default = path is None
    path = Path(path) if path is not None else DEFAULT_STORE
    if used_default:
        _warn_if_other_store_present(path)
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
