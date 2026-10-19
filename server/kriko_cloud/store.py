"""The relay's database: one owner, ciphertext, watches and alerts."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SCHEMA = """
CREATE TABLE IF NOT EXISTS owner (
  token_hash TEXT NOT NULL,
  topic      TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS blobs (
  name       TEXT PRIMARY KEY,
  version    INTEGER NOT NULL,
  body       BLOB NOT NULL,
  updated_at TEXT NOT NULL);
-- A watched page. The address is sealed; `url_hash` is what logs and the API say.
CREATE TABLE IF NOT EXISTS watches (
  watch_id         TEXT PRIMARY KEY,
  url_hash         TEXT NOT NULL,
  url_sealed       BLOB NOT NULL,
  host             TEXT NOT NULL DEFAULT '',
  label            TEXT NOT NULL DEFAULT '',
  target           REAL,
  drop_pct         REAL,
  started_price    REAL,
  currency         TEXT NOT NULL DEFAULT '',
  created_at       TEXT NOT NULL,
  last_checked     TEXT NOT NULL DEFAULT '',
  last_price       REAL,
  last_error       TEXT NOT NULL DEFAULT '',
  fail_count       INTEGER NOT NULL DEFAULT 0,
  last_alert_price REAL,
  last_alert_at    TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS alerts (
  alert_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  watch_id   TEXT NOT NULL,
  kind       TEXT NOT NULL,
  label      TEXT NOT NULL DEFAULT '',
  price      REAL,
  was_price  REAL,
  currency   TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
"""

MAX_BLOBS = 8
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
    """The token is not the owner's, or the relay is not claimed."""


class Claimed(Exception):
    """The relay already has an owner."""


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

    def seal(self, url: str) -> bytes:
        return self._fernet.encrypt(url.encode("utf-8"))

    def unseal(self, sealed: bytes) -> str:
        try:
            return self._fernet.decrypt(bytes(sealed)).decode("utf-8")
        except InvalidToken:
            return ""

    # ── the owner ────────────────────────────────────────────────────────
    def claim(self, token: str, topic: str) -> bool:
        """Take an unclaimed relay. `True` when claimed now; `False` when this token already owns it."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT token_hash FROM owner").fetchone()
            if row:
                if not hmac.compare_digest(row["token_hash"], token_hash(token)):
                    raise Claimed
                conn.execute("UPDATE owner SET topic = COALESCE(NULLIF(?, ''), topic)", (topic,))
                return False
            conn.execute("INSERT INTO owner (token_hash, topic, created_at) VALUES (?, ?, ?)",
                         (token_hash(token), topic, stamp(now())))
            return True

    def check(self, token: str) -> sqlite3.Row:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM owner").fetchone()
        if not row or not hmac.compare_digest(row["token_hash"], token_hash(token)):
            raise Denied
        return row

    def reset(self) -> None:
        """Forget everything and free the relay for a new owner."""
        with self.connect() as conn:
            for table in ("blobs", "watches", "alerts", "owner"):
                conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed names

    # ── blobs ────────────────────────────────────────────────────────────
    def read_blob(self, name: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT version, body, updated_at FROM blobs WHERE name = ?", (name,)).fetchone()

    def write_blob(self, name: str, body: bytes, expect: int | None) -> int:
        """Store `body`. `expect` is the version the caller last read, 0 for none."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT version FROM blobs WHERE name = ?", (name,)).fetchone()
            have = row["version"] if row else 0
            if expect is not None and expect != have:
                raise Conflict(have)
            if not row and conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] >= MAX_BLOBS:
                raise Full("too many blobs")
            version = have + 1
            conn.execute("INSERT INTO blobs (name, version, body, updated_at) VALUES (?, ?, ?, ?)"
                         " ON CONFLICT(name) DO UPDATE SET version = excluded.version, body = excluded.body,"
                         " updated_at = excluded.updated_at", (name, version, body, stamp(now())))
            return version

    # ── watches ──────────────────────────────────────────────────────────
    def put_watch(self, watch_id: str, url: str, host: str, *, label: str, target, drop_pct, started_price,
                  currency: str, limit: int) -> str:
        hashed = url_hash(url)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            known = conn.execute("SELECT url_hash FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
            if not known and conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0] >= limit:
                raise Full("this relay watches as many pages as it may")
            if known and known["url_hash"] != hashed:
                # A different page under the same name: read it fresh.
                conn.execute("DELETE FROM watches WHERE watch_id = ?", (watch_id,))
                known = None
            if known:
                conn.execute("UPDATE watches SET label = ?, target = ?, drop_pct = ?, started_price = ?,"
                             " currency = ? WHERE watch_id = ?",
                             (label[:MAX_LABEL], target, drop_pct, started_price, currency[:8], watch_id))
            else:
                conn.execute(
                    "INSERT INTO watches (watch_id, url_hash, url_sealed, host, label, target, drop_pct,"
                    " started_price, currency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (watch_id, hashed, self.seal(url), host, label[:MAX_LABEL], target, drop_pct, started_price,
                     currency[:8], stamp(now())))
        return hashed

    def drop_watch(self, watch_id: str) -> bool:
        with self.connect() as conn:
            return bool(conn.execute("DELETE FROM watches WHERE watch_id = ?", (watch_id,)).rowcount)

    def watches(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT watch_id, url_hash, label, target, drop_pct, currency, last_price,"
                                " last_checked, last_error FROM watches ORDER BY created_at")
            return [dict(r) for r in rows]

    def alerts_after(self, after: int, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT alert_id, watch_id, kind, label, price, was_price, currency, created_at"
                                " FROM alerts WHERE alert_id > ? ORDER BY alert_id LIMIT ?", (after, limit))
            return [dict(r) for r in rows]
