"""Reading the pages the relay was asked to watch, once each, and telling who cares.

Pages are keyed by the hash of their address, so a page that many groups watch
is fetched once. The rule for what is worth an alert is `app.pricewatch.crossed`
and `worth_repeating`, the same two functions the desktop uses, so a watch means
the same thing wherever it is read.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from app import pricewatch

from . import store as storage

#: A page is re-read this often, doubling for each failure up to sixteen times.
EVERY = timedelta(hours=6)
MAX_BACKOFF = 16
#: Pages fetched in one sweep, so a big backlog is spread over several.
PER_SWEEP = 400
#: Between two fetches from one host.
HOST_PAUSE_S = 2.0


def _parse(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def due(db: storage.Store, at: datetime) -> list[dict]:
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM pages ORDER BY last_checked")]
    out = []
    for row in rows:
        last = _parse(row["last_checked"])
        wait = EVERY * min(2 ** int(row["fail_count"]), MAX_BACKOFF)
        if last is None or at - last >= wait:
            out.append(row)
    return out[:PER_SWEEP]


def sweep(db: storage.Store, fetch: Callable[[str], str], push: Callable[..., bool], *, at: datetime | None = None,
          pause: Callable[[float], None] = time.sleep, ntfy_base: str = "") -> dict:
    """Read every page that is due. Returns `{read, failed, alerts}`."""
    at = at or storage.now()
    read = failed = alerts = 0
    last_host_at: dict[str, float] = {}
    for page in due(db, at):
        url = db.unseal(page["url_sealed"])
        host = page["host"] or urlsplit(url).hostname or ""
        if host in last_host_at:
            gap = HOST_PAUSE_S - (time.monotonic() - last_host_at[host])
            if gap > 0:
                pause(gap)
        offer = pricewatch.read_markup(fetch(url)) if url else {}
        last_host_at[host] = time.monotonic()
        if not offer:
            failed += 1
            with db.connect() as conn:
                conn.execute("UPDATE pages SET last_checked = ?, fail_count = fail_count + 1, last_error = ?"
                             " WHERE url_hash = ?", (storage.stamp(at), "no price could be read", page["url_hash"]))
            continue
        read += 1
        with db.connect() as conn:
            conn.execute("UPDATE pages SET last_checked = ?, last_price = ?, currency = ?, last_error = '',"
                         " fail_count = 0 WHERE url_hash = ?",
                         (storage.stamp(at), offer["price"], offer.get("currency") or "", page["url_hash"]))
            watches = [dict(r) for r in conn.execute(
                "SELECT w.*, g.topic FROM watches w JOIN groups g ON g.group_id = w.group_id"
                " WHERE w.url_hash = ?", (page["url_hash"],))]
        for watch in watches:
            if watch["currency"] and offer.get("currency") and watch["currency"] != offer["currency"]:
                continue
            kind = pricewatch.crossed(offer["price"], target=watch["target"], drop_pct=watch["drop_pct"],
                                      started_price=watch["started_price"])
            if not kind or not pricewatch.worth_repeating(
                    offer["price"], watch["last_alert_price"], _parse(watch["last_alert_at"]), at):
                continue
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO alerts (group_id, watch_id, kind, label, price, was_price, currency, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (watch["group_id"], watch["watch_id"], kind, watch["label"], offer["price"],
                     watch["started_price"], offer.get("currency") or watch["currency"], storage.stamp(at)))
                conn.execute("UPDATE watches SET last_alert_price = ?, last_alert_at = ? WHERE group_id = ?"
                             " AND watch_id = ?", (offer["price"], storage.stamp(at), watch["group_id"],
                                                   watch["watch_id"]))
            alerts += 1
            price = f"{offer['price']:g} {offer.get('currency') or watch['currency']}".strip()
            # No link: a push service is a third party, and the address stays with the relay.
            push(ntfy_base, watch["topic"], "Price dropped", f"{watch['label'] or 'A page you watch'}: {price}")
    return {"read": read, "failed": failed, "alerts": alerts}
