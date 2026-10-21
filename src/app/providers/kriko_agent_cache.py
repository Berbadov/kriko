"""Small persistent TTL cache for Kriko Agent retrieval responses.

Only successful DeepSeek Search/Fetch responses are stored. API keys never
enter the cache key or payload. Rows live in SQLite under Kriko's data folder,
with independent short TTLs and a bounded row count.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

SEARCH_TTL_SECONDS = 15 * 60
FETCH_TTL_SECONDS = 60 * 60
MAX_CACHE_ROWS = 500

_lock = threading.RLock()


def default_path() -> Path:
    from app.web.settings import KRIKO_HOME

    return KRIKO_HOME / "cache" / "kriko-agent.sqlite3"


class RetrievalCache:
    """A thread-safe SQLite cache that can be shared by concurrent runs."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_path()

    @staticmethod
    def _key(lane: str, key: str) -> str:
        return hashlib.sha256(f"{lane}\0{key}".encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS retrieval_cache ("
            "cache_key TEXT PRIMARY KEY, lane TEXT NOT NULL, payload TEXT NOT NULL, "
            "cached_at REAL NOT NULL, expires_at REAL NOT NULL)"
        )
        return conn

    def get(self, lane: str, key: str, *, now: float | None = None) -> dict | None:
        digest = self._key(lane, key)
        at = time.time() if now is None else now
        with _lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload, expires_at FROM retrieval_cache WHERE cache_key = ?",
                (digest,),
            ).fetchone()
            if row is None:
                return None
            if float(row[1]) <= at:
                conn.execute("DELETE FROM retrieval_cache WHERE cache_key = ?", (digest,))
                return None
            try:
                value = json.loads(row[0])
            except (TypeError, ValueError):
                conn.execute("DELETE FROM retrieval_cache WHERE cache_key = ?", (digest,))
                return None
            return value if isinstance(value, dict) else None

    def put(self, lane: str, key: str, payload: dict, *, ttl_seconds: float,
            now: float | None = None) -> None:
        if ttl_seconds <= 0:
            return
        at = time.time() if now is None else now
        digest = self._key(lane, key)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with _lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO retrieval_cache(cache_key, lane, payload, cached_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET "
                "lane=excluded.lane, payload=excluded.payload, cached_at=excluded.cached_at, "
                "expires_at=excluded.expires_at",
                (digest, lane, encoded, at, at + ttl_seconds),
            )
            conn.execute("DELETE FROM retrieval_cache WHERE expires_at <= ?", (at,))
            old = conn.execute(
                "SELECT cache_key FROM retrieval_cache ORDER BY cached_at DESC "
                "LIMIT -1 OFFSET ?",
                (MAX_CACHE_ROWS,),
            ).fetchall()
            if old:
                conn.executemany(
                    "DELETE FROM retrieval_cache WHERE cache_key = ?", old
                )
