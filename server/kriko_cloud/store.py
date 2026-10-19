"""The relay's database: ciphertext, hashed pages, watches and alerts."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
  group_id   TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL,
  topic      TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  last_seen  TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS blobs (
  group_id   TEXT NOT NULL,
  name       TEXT NOT NULL,
  version    INTEGER NOT NULL,
  body       BLOB NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (group_id, name));
-- A page, by the hash of its address. The address itself is sealed.
CREATE TABLE IF NOT EXISTS pages (
  url_hash     TEXT PRIMARY KEY,
  url_sealed   BLOB NOT NULL,
  host         TEXT NOT NULL DEFAULT '',
  last_checked TEXT NOT NULL DEFAULT '',
  last_price   REAL,
  currency     TEXT NOT NULL DEFAULT '',
  last_error   TEXT NOT NULL DEFAULT '',
  fail_count   INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS watches (
  group_id         TEXT NOT NULL,
  watch_id         TEXT NOT NULL,
  url_hash         TEXT NOT NULL,
  label            TEXT NOT NULL DEFAULT '',
  target           REAL,
  drop_pct         REAL,
  started_price    REAL,
  currency         TEXT NOT NULL DEFAULT '',
  created_at       TEXT NOT NULL,
  last_alert_price REAL,
  last_alert_at    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (group_id, watch_id));
CREATE INDEX IF NOT EXISTS watches_page ON watches (url_hash);
CREATE TABLE IF NOT EXISTS alerts (
  alert_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id   TEXT NOT NULL,
  watch_id   TEXT NOT NULL,
  kind       TEXT NOT NULL,
  label      TEXT NOT NULL DEFAULT '',
  price      REAL,
  was_price  REAL,
  currency   TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS alerts_group ON alerts (group_id, alert_id);
"""

NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
MAX_BLOBS_PER_GROUP = 8
MAX_LABEL = 120


def now() -> datetime:
    return datetime.now(UTC)


def stamp(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class Full(Exception):
    """The operator's limit was reached."""


class Conflict(Exception):
    """The blob moved since the caller read it."""


class Denied(Exception):
    """The token does not belong to this group."""


class Store:
    def __init__(self, path: Path | str, secret: str = ""):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        key_file = self.path.with_suffix(".key")
        if secret:
            material = hashlib.sha256(secret.encode("utf-8")).digest()
        elif key_file.exists():
            material = base64.urlsafe_b64decode(key_file.read_text().strip())
        else:
            material = secrets.token_bytes(32)
            key_file.write_text(base64.urlsafe_b64encode(material).decode())
            key_file.chmod(0o600)
        self._fernet = Fernet(base64.urlsafe_b64encode(material))
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextlib.contextmanager
    def connect(self):
        """A connection that commits when the block ends well, rolls back when it does not, and closes."""
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ── addresses are sealed at rest ─────────────────────────────────────
    def seal(self, url: str) -> bytes:
        return self._fernet.encrypt(url.encode("utf-8"))

    def unseal(self, sealed: bytes) -> str:
        try:
            return self._fernet.decrypt(bytes(sealed)).decode("utf-8")
        except InvalidToken:
            return ""

    # ── groups ───────────────────────────────────────────────────────────
    def register(self, group_id: str, token: str, topic: str, *, max_groups: int) -> bool:
        """Create the group, or accept its own token again. `True` when it was created."""
        with self.connect() as conn:
            row = conn.execute("SELECT token_hash FROM groups WHERE group_id = ?", (group_id,)).fetchone()
            if row:
                if not hmac.compare_digest(row["token_hash"], token_hash(token)):
                    raise Denied
                conn.execute("UPDATE groups SET last_seen = ?, topic = COALESCE(NULLIF(?, ''), topic)"
                             " WHERE group_id = ?", (stamp(now()), topic, group_id))
                return False
            if conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0] >= max_groups:
                raise Full("this relay is full")
            conn.execute("INSERT INTO groups (group_id, token_hash, topic, created_at, last_seen)"
                         " VALUES (?, ?, ?, ?, ?)", (group_id, token_hash(token), topic, stamp(now()), stamp(now())))
            return True

    def check(self, group_id: str, token: str) -> sqlite3.Row:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,)).fetchone()
            if not row or not hmac.compare_digest(row["token_hash"], token_hash(token)):
                raise Denied
            conn.execute("UPDATE groups SET last_seen = ? WHERE group_id = ?", (stamp(now()), group_id))
            return row

    def forget_group(self, group_id: str) -> None:
        with self.connect() as conn:
            for table in ("blobs", "watches", "alerts", "groups"):
                conn.execute(f"DELETE FROM {table} WHERE group_id = ?", (group_id,))  # noqa: S608
            self._drop_orphan_pages(conn)

    def forget_idle(self, days: int, at: datetime | None = None) -> int:
        cutoff = stamp((at or now()) - timedelta(days=days))
        with self.connect() as conn:
            idle = [r["group_id"] for r in conn.execute("SELECT group_id FROM groups WHERE last_seen < ?", (cutoff,))]
        for group_id in idle:
            self.forget_group(group_id)
        return len(idle)

    # ── blobs ────────────────────────────────────────────────────────────
    def read_blob(self, group_id: str, name: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT version, body, updated_at FROM blobs WHERE group_id = ? AND name = ?",
                                (group_id, name)).fetchone()

    def write_blob(self, group_id: str, name: str, body: bytes, expect: int | None) -> int:
        """Store `body`. `expect` is the version the caller last read, 0 for none."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT version FROM blobs WHERE group_id = ? AND name = ?", (group_id, name)).fetchone()
            have = row["version"] if row else 0
            if expect is not None and expect != have:
                raise Conflict(have)
            if not row and conn.execute("SELECT COUNT(*) FROM blobs WHERE group_id = ?", (group_id,)).fetchone()[0] \
                    >= MAX_BLOBS_PER_GROUP:
                raise Full("too many blobs")
            version = have + 1
            conn.execute("INSERT INTO blobs (group_id, name, version, body, updated_at) VALUES (?, ?, ?, ?, ?)"
                         " ON CONFLICT(group_id, name) DO UPDATE SET version = excluded.version,"
                         " body = excluded.body, updated_at = excluded.updated_at",
                         (group_id, name, version, body, stamp(now())))
            return version

    # ── watches ──────────────────────────────────────────────────────────
    def put_watch(self, group_id: str, watch_id: str, url: str, host: str, *, label: str, target, drop_pct,
                  started_price, currency: str, max_per_group: int, max_pages: int) -> str:
        hashed = url_hash(url)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            known = conn.execute("SELECT 1 FROM watches WHERE group_id = ? AND watch_id = ?",
                                 (group_id, watch_id)).fetchone()
            if not known and conn.execute("SELECT COUNT(*) FROM watches WHERE group_id = ?", (group_id,)).fetchone()[0] \
                    >= max_per_group:
                raise Full("this group watches as many pages as it may")
            if not conn.execute("SELECT 1 FROM pages WHERE url_hash = ?", (hashed,)).fetchone():
                if conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] >= max_pages:
                    raise Full("this relay watches as many pages as it can")
                conn.execute("INSERT INTO pages (url_hash, url_sealed, host) VALUES (?, ?, ?)",
                             (hashed, self.seal(url), host))
            conn.execute(
                "INSERT INTO watches (group_id, watch_id, url_hash, label, target, drop_pct, started_price,"
                " currency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(group_id, watch_id) DO UPDATE SET url_hash = excluded.url_hash,"
                " label = excluded.label, target = excluded.target, drop_pct = excluded.drop_pct,"
                " started_price = excluded.started_price, currency = excluded.currency",
                (group_id, watch_id, hashed, label[:MAX_LABEL], target, drop_pct, started_price, currency[:8],
                 stamp(now())))
            self._drop_orphan_pages(conn)
        return hashed

    def drop_watch(self, group_id: str, watch_id: str) -> bool:
        with self.connect() as conn:
            gone = conn.execute("DELETE FROM watches WHERE group_id = ? AND watch_id = ?",
                                (group_id, watch_id)).rowcount
            self._drop_orphan_pages(conn)
            return bool(gone)

    def watches_of(self, group_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT w.watch_id, w.url_hash, w.label, w.target, w.drop_pct, w.currency, p.last_price,"
                " p.last_checked, p.last_error FROM watches w JOIN pages p ON p.url_hash = w.url_hash"
                " WHERE w.group_id = ? ORDER BY w.created_at", (group_id,))
            return [dict(r) for r in rows]

    @staticmethod
    def _drop_orphan_pages(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM pages WHERE url_hash NOT IN (SELECT url_hash FROM watches)")

    # ── alerts ───────────────────────────────────────────────────────────
    def alerts_after(self, group_id: str, after: int, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT alert_id, watch_id, kind, label, price, was_price, currency, created_at"
                                " FROM alerts WHERE group_id = ? AND alert_id > ? ORDER BY alert_id LIMIT ?",
                                (group_id, after, limit))
            return [dict(r) for r in rows]
