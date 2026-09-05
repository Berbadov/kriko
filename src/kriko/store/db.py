"""SQLite connection handling for pack files and the installed store.

One schema serves both (see `schema.sql`), so this module makes no distinction
between them — `connect()` opens either.

No ORM: the pack format *is* SQLite, and a pack file is meant to be openable
by anything that speaks it, so dialect portability is not a goal here.
"""

import hashlib
import sqlite3
import sys
import time
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_VERSION = 1

#: How long a connection waits for a lock before giving up. Generous: the
#: writers here are a pack install and a pipeline subprocess, and a reader
#: who waits half a second beats a reader who is told the app is broken.
BUSY_TIMEOUT_MS = 5000
WAL_ATTEMPTS = 5
WAL_RETRY_SECONDS = 0.05

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


def schema_stamp(schema: str) -> int:
    """A fingerprint of a schema, small enough for SQLite's `user_version`.

    31 bits of a SHA-256, because `user_version` is a signed 32-bit integer and
    a negative one is awkward to compare. Collisions do not matter here in the
    way they would for a security hash: the worst case is a schema edit that
    happens to fingerprint identically to the previous one and is therefore not
    re-applied, at odds of one in two billion per edit.

    Deliberately *not* `SCHEMA_VERSION`. That number means something to a
    reader — `/api/health` reports it — and changes on its own schedule.
    """
    digest = hashlib.sha256(schema.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def connect(path=None, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a store or pack file, applying the schema if it is new.

    WAL is set from the first connection because the web app reads while
    pipeline subprocesses write to the same file. Under the default rollback
    journal that is an `SQLITE_BUSY` waiting to happen; today's code only avoids
    it by using two separate database files.

    `check_same_thread=False` because a connection here is owned by *one* piece
    of work, not by one thread, and those are not the same thing under a web
    server. FastAPI runs a synchronous generator dependency by splitting it
    across the AnyIO worker pool: `connect()` happens in one `run_in_threadpool`
    call and the endpoint body in another, with no promise the pool hands back
    the same worker. With a single idle worker it always does — which is why a
    sequential sweep, a `TestClient` test and the packaging smoke check all pass
    — and the moment a browser fires six requests at once the pool spreads them
    and every connection is used off the thread that opened it. That shipped in
    0.3.1 as `sqlite3.ProgrammingError` behind an anonymous 500 on every
    store-backed view.

    This is safe rather than a suppressed warning: `sqlite3.threadsafety` is 3
    (serialized), a connection is closed by the same dependency that opened it,
    and no two threads ever hold one at the same moment. The check being
    disabled is the *statement* that ownership is per-request; the sequencing is
    what makes it true.
    """
    used_default = path is None
    path = Path(path) if path is not None else DEFAULT_STORE
    if used_default:
        _warn_if_other_store_present(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if read_only:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, check_same_thread=False
        )
    else:
        conn = sqlite3.connect(path, check_same_thread=False)

    conn.row_factory = sqlite3.Row
    # Wait for a lock instead of failing on one. Without this, two connections
    # opening at the same moment — which is every view in the app, since each
    # one fires its requests together — raced each other to `database is
    # locked` before either had read a row.
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    if not read_only:
        _prepare(conn)
    return conn


def _prepare(conn: sqlite3.Connection) -> None:
    """Make a writable connection usable, doing as little as possible.

    This used to set the journal mode and run the entire schema on *every*
    connection. Both are writes. Applying 32 idempotent `CREATE TABLE IF NOT
    EXISTS` statements is nearly free in wall-clock terms and completely not
    free in lock terms: it made every read request a writer holding an
    exclusive lock, so a handful of simultaneous reads deadlined each other out
    and the reader saw a 500 on every view at once.

    So both writes are now conditional on a read:

    * `journal_mode` is already WAL on the second and every later connection,
      and asking is a read. Only the first one on a fresh file changes it, and
      that is retried rather than surrendered — a `PRAGMA` that wants an
      exclusive lock does not always defer to `busy_timeout`, and losing this
      race means silently running under the rollback journal, which is the
      concurrency problem this line exists to prevent.
    * The schema is applied once per *database*, not once per connection, and
      what marks it applied is a fingerprint of the schema file itself rather
      than a version number somebody has to remember to bump. Edit `schema.sql`
      and every existing store re-runs it on its next connection; every
      statement in it is `IF NOT EXISTS`, so that adds what is new and touches
      nothing else. A hand-maintained number would have been one more manual
      step to forget, and forgetting it means a store that silently never gains
      the table the new code queries.
    """
    if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        _set_wal(conn)
    conn.execute("PRAGMA synchronous = NORMAL")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    stamp = schema_stamp(schema)
    if conn.execute("PRAGMA user_version").fetchone()[0] != stamp:
        conn.executescript(schema)
        conn.execute(f"PRAGMA user_version = {stamp}")
        conn.commit()


def _set_wal(conn: sqlite3.Connection) -> None:
    """Switch to WAL, tolerating the other connections doing it at once.

    Bounded and quiet on the last attempt: if some other connection won the
    race the file is already in WAL, and if nothing did, a store on a rollback
    journal still works — it is slower under concurrency, not broken. Raising
    here would turn a contended first-run into a dead application.
    """
    for attempt in range(WAL_ATTEMPTS):
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError:
            if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
                return
            if attempt == WAL_ATTEMPTS - 1:
                return
            time.sleep(WAL_RETRY_SECONDS)


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
