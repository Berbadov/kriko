"""One number that moves when the knowledge does (B152.4).

"A card added by the agent, we instantly see the new card" needs something
cheap to watch. The writers are not all in this process: the reader's agent
writes through the MCP server, a separate process, and a job writes on its own
connection. `PRAGMA data_version` answers exactly that question: it changes
on a connection when *any other connection* has committed to the file since
it last asked. So one read-only connection is held for the app's lifetime, and
every change it sees moves the clock one tick.

The value is `"<boot>-<tick>"`, not a bare count: a restarted app starts
counting again, and a client comparing a number it held from before the
restart must see a different value, not possibly the same one.
"""

import secrets
import sqlite3
import threading
from pathlib import Path

from kriko.store.db import connect


class KnowledgeClock:
    def __init__(self, store_path: Path | str):
        self._path = Path(store_path)
        self._boot = secrets.token_hex(3)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._seen: int | None = None
        self._tick = 0

    def now(self) -> str:
        """The current reading. Never raises: a store that cannot be opened
        yet (a fresh install before seeding) reads as an unchanged clock."""
        with self._lock:
            try:
                if self._conn is None:
                    if not self._path.exists():
                        return self._stamp()
                    self._conn = connect(self._path, read_only=True)
                version = self._conn.execute("PRAGMA data_version").fetchone()[0]
            except sqlite3.Error:
                self._drop()
                return self._stamp()
            if self._seen is not None and version != self._seen:
                self._tick += 1
            self._seen = version
            return self._stamp()

    def close(self) -> None:
        with self._lock:
            self._drop()

    def _drop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
        self._conn = None
        self._seen = None

    def _stamp(self) -> str:
        return f"{self._boot}-{self._tick}"
