"""Remember search answers, and cap how many one look may cost.

Free SERP endpoints answer a handful of queries from one address before they
challenge it. A look asks the same question more than once — a repeat, a retry,
a second reader on the same product — and paying for it twice is what turns a
throttle into a failure. This wraps a searcher (`search(query, limit)`) with an
on-disk answer cache and an optional per-instance budget.

The cache is a fact about the world for a week, not a promise: a product's
pages do not change between two looks on a Tuesday. Keys are the engine (when
the searcher names one), the query and the limit, so a look that asks for four
results never serves a five-result answer.

A failure is never cached: a 502 is a fact about this minute.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

DEFAULT_TTL = 7 * 24 * 3600
DEFAULT_BUDGET = 0  # 0 means no cap
SCHEMA = """CREATE TABLE IF NOT EXISTS answers (
    key TEXT PRIMARY KEY,
    hits TEXT NOT NULL,
    asked_at REAL NOT NULL
)"""


class BudgetExhausted(Exception):
    """The look asked for more searches than it was allowed."""


def _key(searcher, query: str, limit: int) -> str:
    engine = getattr(searcher, "engines", None)
    name = ",".join(engine) if isinstance(engine, list) else str(engine or "")
    return hashlib.sha256(f"{name}|{limit}|{query}".encode("utf-8")).hexdigest()


def _read(conn: sqlite3.Connection, key: str, ttl: float) -> list[dict] | None:
    row = conn.execute("SELECT hits, asked_at FROM answers WHERE key = ?",
                       (key,)).fetchone()
    if row is None or time.time() - float(row[1]) > ttl:
        return None
    try:
        hits = json.loads(row[0])
    except ValueError:
        return None
    return hits if isinstance(hits, list) else None


def _write(conn: sqlite3.Connection, key: str, hits: list[dict]) -> None:
    conn.execute("INSERT OR REPLACE INTO answers (key, hits, asked_at) VALUES (?, ?, ?)",
                 (key, json.dumps(hits, ensure_ascii=False), time.time()))
    conn.commit()


def cached(searcher, *, path: Path, ttl: float = DEFAULT_TTL,
           budget: int = DEFAULT_BUDGET):
    """`search(query, limit)` that answers from disk when it can.

    `budget` counts misses only: a cached answer is free, so a repeat look is
    never blocked by a quota it did not spend.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # The inner searcher counts what it actually asked; this adds how many of
    # those were misses. Sharing the dict keeps `search.stats["hits"]` live for
    # the callers that already read it.
    stats = getattr(searcher, "stats", None)
    if not isinstance(stats, dict):
        stats = {}
    stats.setdefault("misses", 0)

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(SCHEMA)
        return conn

    def search(query: str, limit: int = 5, **kwargs) -> list[dict]:
        conn = connect()
        try:
            key = _key(searcher, query, limit)
            remembered = _read(conn, key, ttl)
            if remembered is not None:
                return remembered
            if budget and stats["misses"] >= budget:
                raise BudgetExhausted(
                    f"this look already asked {stats['misses']} question(s) "
                    f"and {query!r} was one more")
            stats["misses"] += 1
            hits = searcher(query, limit, **kwargs)
            if isinstance(hits, list):
                _write(conn, key, hits)
            return hits
        finally:
            conn.close()

    search.stats = stats  # type: ignore[attr-defined]
    return search
