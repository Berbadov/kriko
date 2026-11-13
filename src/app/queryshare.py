"""The reader's opt-in to share which products they looked up.

Off by default, and while it is off this module queues nothing and sends
nothing. Turned on in Settings, it sends what the catalog was *asked* — the
product model the reader looked up, already resolved to an identity by the
engine, and whether the catalog had it — so the project knows which products to
cover next. Nothing else travels: not the listing link, not the page title, not
a time, not an install id.

**The query is built from identity, never from a page.** `q` is the lowercase
brand and model (and series, where a catalog names its model that way), read
from the keys the pack declared. A lookup whose identity resolved no brand and
model sends nothing at all, because a listing title is the reader's page, not a
product.

**Fail quiet**, like the update check and the daily ping: a machine with no
network gets nothing, the request has a short timeout, and every error is
swallowed. The queue is memory only, holds no timestamps, and is emptied the
moment the reader turns the setting off.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from urllib.parse import urlparse

from app import prefs

log = logging.getLogger(__name__)

#: Where the batches go. One constant, overridable for tests and for a fork
#: that runs its own gateway.
GATEWAY = "https://kriko-gateway.fly.dev"


def endpoint() -> str:
    base = os.environ.get("KRIKO_QUERIES_URL") or GATEWAY
    return base.rstrip("/") + "/v1/queries"

#: Generic on purpose: no version, no host, nothing that tells two machines
#: apart.
USER_AGENT = "kriko"
TIMEOUT = 5
#: What the gateway takes in one request, and how often a batch may go.
BATCH = 20
INTERVAL = 60

#: The gateway's own rules for `q`, applied here so a value it would drop is
#: never queued in the first place.
_QUERY = re.compile(r"^[a-z0-9][a-z0-9 .+\-/_]*$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._\-/]*$")
QUERY_MIN, QUERY_MAX = 3, 120
ID_MAX = 80
#: Identity keys that name a product's model, in the order they are read. A
#: catalog names its model `model` or `series`; both are closed vocabulary
#: about how a product is named, not a list of products.
MODEL_KEYS = ("model", "series")

_queue: list[dict] = []
_lock = threading.Lock()
_last_sent = 0.0


def enabled(conn) -> bool:
    """The reader turned it on. Unset, empty or anything but "1" is off."""
    return str(prefs.read(conn).get(prefs.SHARE_QUERIES) or "").strip() == "1"


def normalize(identity: dict) -> str:
    """`brand model [model]`, lowercase, or `""` when no brand+model resolved."""
    values = {str(k).strip().lower(): str(v or "").strip() for k, v in (identity or {}).items()}
    brand = values.get("brand", "")
    model = next((values[key] for key in MODEL_KEYS if values.get(key)), "")
    if not brand or not model:
        return ""
    text = " ".join(f"{brand} {model}".lower().split())
    if not QUERY_MIN <= len(text) <= QUERY_MAX or not _QUERY.match(text):
        return ""
    return text


def _ident(value) -> str:
    text = str(value or "").strip().lower()
    return text if len(text) <= ID_MAX and _ID.match(text) else ""


def record(request, query_identity, outcome, report=None, category=None) -> bool:
    """Queue one lookup, when the reader opted in. Returns whether it was queued.

    `request` is the live HTTP request, read only for where this installation's
    own settings live. `query_identity` is the identity the engine resolved —
    the pack's own identity keys — and never a listing title or a URL.
    `outcome` is `hit` when a catalog subject matched and `miss` when it did
    not; `report` is the subject id the reader opened, and is only sent with a
    hit.
    """
    from app.web import state

    if outcome not in ("hit", "miss"):
        return False
    q = normalize(query_identity)
    if not q:
        return False
    # Read through the request's own app state: the same door every other
    # preference uses, so a test app pointed at a temporary store sees its own
    # setting and never the reader's. An unreadable store is off.
    try:
        conn = state.connect(request.app.state.settings.app_state_path)
        try:
            if not enabled(conn):
                return False
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — sharing is never worth a failed lookup
        return False
    item = {"q": q, "outcome": outcome}
    if outcome == "hit" and _ident(report):
        item["report"] = _ident(report)
    if _ident(category):
        item["category"] = _ident(category)
    with _lock:
        if item not in _queue:
            _queue.append(item)
    _start_flush()
    return True


def clear() -> None:
    """Empty the queue: what turning the setting off does."""
    with _lock:
        _queue.clear()


def pending() -> list[dict]:
    with _lock:
        return list(_queue)


def _take() -> list[dict]:
    with _lock:
        batch, _queue[:] = _queue[:BATCH], []
        return batch


def _restore(batch: list[dict]) -> None:
    with _lock:
        _queue[:0] = batch


def _open(url: str, body: bytes, timeout: int):
    if urlparse(url).scheme != "https":
        raise ValueError(f"refusing a non-https query URL: {url!r}")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — scheme checked

def flush() -> bool:
    """Send one batch, at most once a minute. Never raises; False when nothing went."""
    global _last_sent
    batch = _take()
    if not batch:
        return False
    if time.monotonic() - _last_sent < INTERVAL:
        _restore(batch)
        return False
    _last_sent = time.monotonic()
    body = json.dumps({"queries": batch}).encode()
    try:
        _open(endpoint(), body, TIMEOUT).close()
    except Exception as cause:  # noqa: BLE001 — a shared query is never a failure the reader sees
        log.info("query share failed: %s", cause)
        return False
    return True


def _start_flush() -> None:
    if os.environ.get("KRIKO_NO_QUERY_SHARE"):
        return
    threading.Thread(target=flush, name="query-share", daemon=True).start()
