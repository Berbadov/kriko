"""Kriko's relay, from the desktop's side: pairing, sealed sync, cloud watches, alerts.

The relay (`server/kriko_cloud`) lets a phone and a computer share what the reader
keeps, and watches a price while the computer is off. This module is everything
the desktop does with it, and the rule it keeps is the relay's: tell it as little
as the job needs.

* **One relay, one reader, one key held by the devices.** Pairing makes 32 random
  bytes and keeps them in this app's state. Everything else is derived from them:
  the token that proves you own the relay, the key that seals what is stored, and
  the push topic. The relay is never sent the key, so it stores ciphertext it cannot
  read, and a phone joins by being handed the key (`pairing_code`), not by an
  account. The first device claims the relay with the operator's setup word.
* **Sealed with AES-256-GCM**, the blob's name bound in as associated data so a
  profile cannot be swapped for a ledger.
* **A cloud watch is the one thing the relay must be told.** A server that re-reads a
  page has to know the page; hashing an address cannot change that. So a watch goes
  to the relay only when the reader turns that watch on, and with private labels
  the relay is not even told what the product is called, only that a page it holds
  crossed a price.
* **Merging, not overwriting.** Profile by the later edit; purchases and watches as a
  union, newest row winning, with a short list of deletions so a stopped watch stays
  stopped on every device.

The relay only ever sees an HTTPS address (or a loopback one, for a relay on the same
computer): a key-derived token is never sent in the clear.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app import buyer, pricewatch
from app.providers import network
from app.web import state

SERVER, KEY, PRIVATE_LABELS = "cloud_server", "cloud_key", "cloud_private_labels"
VERSIONS, CURSOR, SYNCED, TOMBS = "cloud_versions", "cloud_alert_cursor", "cloud_synced_at", "cloud_tombstones"
PROFILE_AT = "buyer_profile_at"

PREFIX = "kriko-pair"
MAX_RESPONSE = 1 << 20
TOMBSTONE_DAYS = 90
MAX_TOMBSTONES = 200
GENERIC_LABEL = "A page you watch"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

Http = Callable[[str, str, bytes | None, dict], tuple[int, dict, bytes]]


class RelayError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


# ── keys: one secret, everything derived ─────────────────────────────────


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_key() -> str:
    return _b64(secrets.token_bytes(32))


def _derive(key: str, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=b"kriko/" + info).derive(_unb64(key))


class Keys:
    """Everything a device derives from the one secret it was paired with."""

    def __init__(self, key: str):
        if len(_unb64(key)) != 32:
            raise ValueError("that is not a Kriko sync key")
        self.token = _b64(_derive(key, b"token", 32))
        self.topic = "kriko-" + _derive(key, b"topic", 16).hex()
        self._aead = AESGCM(_derive(key, b"enc", 32))

    def seal(self, name: str, value) -> bytes:
        nonce = secrets.token_bytes(12)
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return b"K1" + nonce + self._aead.encrypt(nonce, data, name.encode("utf-8"))

    def unseal(self, name: str, blob: bytes):
        if not blob.startswith(b"K1") or len(blob) < 2 + 12 + 16:
            raise ValueError("not a sealed Kriko blob")
        try:
            return json.loads(self._aead.decrypt(blob[2:14], blob[14:], name.encode("utf-8")))
        except Exception as error:  # noqa: BLE001 - a wrong key and a damaged blob look the same, and are the same
            raise ValueError("could not open it: wrong key, or it was changed") from error


def cloud_id(product_key: str) -> str:
    """The relay's name for a watch: the same on every device that watches the same page."""
    return hashlib.sha256(product_key.encode("utf-8")).hexdigest()[:24]


# ── pairing ─────────────────────────────────────────────────────────────


def pairing_code(server: str, key: str) -> str:
    return f"{PREFIX}:{_b64(server.encode('utf-8'))}:{key}"


def parse_code(code: str) -> tuple[str, str]:
    parts = str(code or "").strip().split(":")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise ValueError("that is not a Kriko pairing code")
    try:
        server = _unb64(parts[1]).decode("utf-8")
    except Exception as error:  # noqa: BLE001
        raise ValueError("that is not a Kriko pairing code") from error
    Keys(parts[2])
    return secure(server), parts[2]


def secure(server: str) -> str:
    """The relay's address, or `ValueError` if it would send a token in the clear."""
    parts = urlsplit(str(server or "").strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        raise ValueError("the relay's address is a web address, like https://relay.example")
    if parts.scheme == "http" and host not in LOOPBACK:
        raise ValueError("the relay must use https: a plain address would send your token in the clear")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


# ── talking to the relay ────────────────────────────────────────────────


def _urllib(method: str, url: str, data: bytes | None, headers: dict) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with network.urlopen(request, timeout=20) as response:
            return response.status, dict(response.headers), response.read(MAX_RESPONSE)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read(1 << 16)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RelayError("the relay does not answer") from error


class Relay:
    def __init__(self, server: str, key: str, http: Http | None = None):
        self.server = secure(server)
        self.keys = Keys(key)
        self.http = http or _urllib

    def call(self, method: str, path: str, *, body: bytes | None = None, json_body=None,
             extra: dict | None = None, ok: tuple[int, ...] = (200,)) -> tuple[int, dict, bytes]:
        headers = {"Authorization": f"Bearer {self.keys.token}", **(extra or {})}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif body is not None:
            headers["Content-Type"] = "application/octet-stream"
        status, reply_headers, data = self.http(method, f"{self.server}/v1{path}", body, headers)
        if status not in ok:
            detail = ""
            try:
                detail = str(json.loads(data).get("detail", ""))
            except (ValueError, AttributeError):
                pass
            raise RelayError(detail or f"the relay answered {status}", status)
        return status, reply_headers, data

    def claim(self, setup: str = "") -> bool:
        """Take the relay with the operator's setup word, or confirm it is already ours. `True` when taken now."""
        _, _, data = self.call("PUT", "/owner", json_body={"topic": self.keys.topic},
                               extra={"X-Kriko-Setup": setup} if setup else None)
        return bool(json.loads(data).get("claimed"))

    def get_blob(self, name: str) -> tuple[int, object] | None:
        try:
            _, headers, data = self.call("GET", f"/blob/{name}")
        except RelayError as error:
            if error.status == 404:
                return None
            raise
        lowered = {k.lower(): v for k, v in headers.items()}
        return int(lowered.get("x-kriko-version", "0")), self.keys.unseal(name, data)

    def put_blob(self, name: str, value, expect: int) -> int:
        _, _, data = self.call("PUT", f"/blob/{name}", body=self.keys.seal(name, value),
                               extra={"X-Kriko-Expect": str(expect)})
        return int(json.loads(data)["version"])

    def put_watch(self, watch_id: str, **fields) -> None:
        self.call("PUT", f"/watch/{watch_id}", json_body=fields)

    def drop_watch(self, watch_id: str) -> None:
        self.call("DELETE", f"/watch/{watch_id}", ok=(200, 404))

    def watches(self) -> list[dict]:
        return json.loads(self.call("GET", "/watches")[2])["items"]

    def alerts(self, after: int) -> list[dict]:
        return json.loads(self.call("GET", f"/alerts?after={after}")[2])["items"]

    def forget(self) -> None:
        self.call("DELETE", "/owner", ok=(200, 403, 404))


# ── this app's side ──────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(at: datetime | None = None) -> str:
    return (at or _now()).isoformat(timespec="seconds")


def configured(conn: sqlite3.Connection) -> tuple[str, str] | None:
    have = state.all_settings(conn)
    server, key = have.get(SERVER), have.get(KEY)
    return (server, key) if isinstance(server, str) and isinstance(key, str) and server and key else None


def relay_for(conn: sqlite3.Connection, http: Http | None = None) -> Relay | None:
    found = configured(conn)
    return Relay(found[0], found[1], http) if found else None


def status(conn: sqlite3.Connection) -> dict:
    have = state.all_settings(conn)
    found = configured(conn)
    if not found:
        return {"connected": False, "server": "", "watching": 0, "private_labels": False, "synced_at": ""}
    watching = conn.execute("SELECT COUNT(*) FROM watches WHERE cloud = 1").fetchone()[0]
    return {"connected": True, "server": found[0], "watching": watching,
            "private_labels": bool(have.get(PRIVATE_LABELS)), "synced_at": have.get(SYNCED, ""),
            "topic": Keys(found[1]).topic}


def connect(conn: sqlite3.Connection, server: str, *, setup: str = "", private_labels: bool = False,
            http: Http | None = None) -> dict:
    """Claim this relay for this reader with the operator's setup word. Whatever was paired before is left."""
    server = secure(server)
    key = new_key()
    Relay(server, key, http).claim(setup)
    state.put_settings(conn, {SERVER: server, KEY: key, PRIVATE_LABELS: private_labels, VERSIONS: {}, CURSOR: 0,
                              SYNCED: "", TOMBS: []})
    return status(conn)


def join(conn: sqlite3.Connection, code: str, *, http: Http | None = None) -> dict:
    """Join the relay a code names, from a phone or another computer."""
    server, key = parse_code(code)
    Relay(server, key, http).claim()
    state.put_settings(conn, {SERVER: server, KEY: key, VERSIONS: {}, CURSOR: 0, SYNCED: "", TOMBS: []})
    return status(conn)


def code_for(conn: sqlite3.Connection) -> str:
    found = configured(conn)
    if not found:
        raise ValueError("not connected to a relay")
    return pairing_code(*found)


def disconnect(conn: sqlite3.Connection, *, forget_remote: bool = True, http: Http | None = None) -> None:
    relay = relay_for(conn, http)
    if relay and forget_remote:
        try:
            relay.forget()
        except RelayError:
            pass
    for key in (SERVER, KEY, PRIVATE_LABELS, VERSIONS, CURSOR, SYNCED, TOMBS):
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.execute("UPDATE watches SET cloud = 0")
    conn.commit()


# ── deletions, so a stopped watch stays stopped on every device ───────────


def note_deleted(conn: sqlite3.Connection, kind: str, key: str) -> None:
    """Remember a deletion, but only for a reader who has paired a device."""
    note_deleted_many(conn, kind, [key])


def note_deleted_many(conn: sqlite3.Connection, kind: str, keys: list[str]) -> None:
    """`note_deleted` for a whole table at once, in one write."""
    if not keys or not configured(conn):
        return
    cutoff = _stamp(_now() - timedelta(days=TOMBSTONE_DAYS))
    gone = {(kind, key) for key in keys}
    kept = [t for t in (state.all_settings(conn).get(TOMBS) or []) if t["at"] >= cutoff and (t["kind"], t["key"]) not in gone]
    at = _stamp()
    kept += [{"kind": kind, "key": key, "at": at} for key in keys]
    state.put_settings(conn, {TOMBS: kept[-MAX_TOMBSTONES:]})


def _tombs(conn: sqlite3.Connection, kind: str) -> dict[str, str]:
    return {t["key"]: t["at"] for t in (state.all_settings(conn).get(TOMBS) or []) if t["kind"] == kind}


# ── the three blobs ─────────────────────────────────────────────────────


def _canon(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _profile_local(conn) -> dict:
    return {"profile": buyer.read(conn), "at": state.all_settings(conn).get(PROFILE_AT, "")}


def _profile_merge(conn, local: dict, remote: dict | None) -> dict:
    if not remote or remote.get("at", "") <= local["at"]:
        return local
    buyer.save(conn, remote["profile"], at=remote["at"])
    return remote


def _ledger_local(conn) -> dict:
    return {"purchases": buyer.purchases(conn, 500), "deleted": [{"key": k, "at": a} for k, a in _tombs(conn, "purchase").items()]}


def _ledger_merge(conn, local: dict, remote: dict | None) -> dict:
    gone = {t["key"]: t["at"] for t in local["deleted"] + ((remote or {}).get("deleted") or [])}
    rows = {r["purchase_id"]: r for r in (remote or {}).get("purchases", [])}
    for row in local["purchases"]:
        have = rows.get(row["purchase_id"])
        if not have or (row["answered_at"], row["bought_at"]) >= (have["answered_at"], have["bought_at"]):
            rows[row["purchase_id"]] = row
    for pid in gone:
        rows.pop(pid, None)
    for pid in [r["purchase_id"] for r in buyer.purchases(conn, 500) if r["purchase_id"] in gone]:
        buyer.forget_purchase(conn, pid, remember=False)
    for row in rows.values():
        buyer.adopt_purchase(conn, row)
    return {"purchases": sorted(rows.values(), key=lambda r: r["purchase_id"]),
            "deleted": [{"key": k, "at": a} for k, a in sorted(gone.items())]}


_WATCH_FIELDS = ("product_key", "url", "name", "currency", "target", "drop_pct", "started_price", "cloud", "updated_at")


def _watches_local(conn) -> dict:
    rows = [{k: row[k] for k in _WATCH_FIELDS} for row in pricewatch.watches(conn)]
    return {"watches": rows, "deleted": [{"key": k, "at": a} for k, a in _tombs(conn, "watch").items()]}


def _watches_merge(conn, local: dict, remote: dict | None) -> dict:
    gone = {t["key"]: t["at"] for t in local["deleted"] + ((remote or {}).get("deleted") or [])}
    rows = {r["product_key"]: r for r in (remote or {}).get("watches", [])}
    for row in local["watches"]:
        have = rows.get(row["product_key"])
        if not have or row["updated_at"] >= have["updated_at"]:
            rows[row["product_key"]] = row
    for key, at in gone.items():
        if key in rows and rows[key]["updated_at"] <= at:
            del rows[key]
    for row in pricewatch.watches(conn):
        if row["product_key"] in gone and row["updated_at"] <= gone[row["product_key"]]:
            pricewatch.unwatch(conn, row["watch_id"], remember=False)
    for row in rows.values():
        pricewatch.adopt(conn, row)
    return {"watches": sorted(rows.values(), key=lambda r: r["product_key"]),
            "deleted": [{"key": k, "at": a} for k, a in sorted(gone.items())]}


BLOBS = (("profile", _profile_local, _profile_merge), ("ledger", _ledger_local, _ledger_merge),
         ("watches", _watches_local, _watches_merge))


def sync_blobs(conn: sqlite3.Connection, relay: Relay) -> dict:
    """Bring this app and the relay to the same state. Returns what moved each way."""
    versions = dict(state.all_settings(conn).get(VERSIONS) or {})
    moved: dict[str, list[str]] = {"pulled": [], "pushed": []}
    for name, local_of, merge in BLOBS:
        for attempt in range(2):
            found = relay.get_blob(name)
            remote_version, remote = (found[0], found[1]) if found else (0, None)
            before = _canon(local_of(conn))
            merged = merge(conn, local_of(conn), remote if isinstance(remote, dict) else None)
            if _canon(merged) != before and name not in moved["pulled"]:
                moved["pulled"].append(name)
            if remote is not None and _canon(merged) == _canon(remote):
                versions[name] = remote_version
                break
            try:
                versions[name] = relay.put_blob(name, merged, remote_version)
                moved["pushed"].append(name)
                break
            except RelayError as error:
                if error.status != 409 or attempt:
                    raise
    state.put_settings(conn, {VERSIONS: versions})
    return moved


# ── cloud watches and the alerts they raise ─────────────────────────────


def sync_watches(conn: sqlite3.Connection, relay: Relay) -> dict:
    """Make the relay watch exactly the pages this reader turned the cloud on for."""
    private = bool(state.all_settings(conn).get(PRIVATE_LABELS))
    want = {cloud_id(w["product_key"]): w for w in pricewatch.watches(conn) if w["cloud"]}
    have = {w["watch_id"] for w in relay.watches()}
    for wid, watch in want.items():
        relay.put_watch(wid, url=watch["url"], label=GENERIC_LABEL if private else (watch["name"] or GENERIC_LABEL),
                        target=watch["target"], drop_pct=watch["drop_pct"], started_price=watch["started_price"],
                        currency=watch["currency"])
    for wid in sorted(have - set(want)):
        relay.drop_watch(wid)
    return {"watching": len(want), "stopped": len(have - set(want))}


def pull_alerts(conn: sqlite3.Connection, relay: Relay) -> int:
    """Alerts the relay raised while this computer was off, as ordinary local alerts."""
    cursor = int(state.all_settings(conn).get(CURSOR) or 0)
    local = {cloud_id(w["product_key"]): w for w in pricewatch.watches(conn)}
    added = 0
    for item in relay.alerts(cursor):
        cursor = max(cursor, int(item["alert_id"]))
        watch = local.get(item["watch_id"])
        if not watch:
            continue
        done = conn.execute(
            "INSERT OR IGNORE INTO watch_alerts (alert_id, watch_id, kind, name, url, price, was_price, currency,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"cloud-{item['alert_id']}", watch["watch_id"], item["kind"], watch["name"], watch["url"],
             item["price"], item["was_price"], item["currency"], item["created_at"]))
        added += done.rowcount
    conn.commit()
    state.put_settings(conn, {CURSOR: cursor})
    return added


def sync(conn: sqlite3.Connection, http: Http | None = None) -> dict:
    """One full pass: sealed blobs, cloud watches, alerts. Raises `RelayError` if the relay is unreachable."""
    relay = relay_for(conn, http)
    if not relay:
        raise ValueError("not connected to a relay")
    relay.claim()
    out: dict[str, object] = {"blobs": sync_blobs(conn, relay)}
    out["watches"] = sync_watches(conn, relay)
    out["alerts"] = pull_alerts(conn, relay)
    state.put_settings(conn, {SYNCED: _stamp()})
    return out


def sync_quietly(conn: sqlite3.Connection, http: Http | None = None) -> dict | None:
    """`sync`, for a clock: nothing to do when not connected, and a relay that is down is not an error."""
    if not configured(conn):
        return None
    try:
        return sync(conn, http)
    except (RelayError, ValueError):
        return None


def default_server() -> str:
    """A relay address the operator has put in the environment, to offer in the form."""
    return os.environ.get("KRIKO_RELAY", "")
