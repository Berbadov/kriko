"""Reading the pages the relay was asked to watch, and telling the owner.

The rule for what is worth an alert is `app.pricewatch.crossed` and
`worth_repeating`, the same two functions the desktop uses, so a watch means the
same thing wherever it is read.
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
PER_SWEEP = 200
#: Between two fetches from one host.
HOST_PAUSE_S = 2.0


def _parse(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def due(db: storage.Store, at: datetime) -> list[dict]:
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM watches ORDER BY last_checked")]
    out = []
    for row in rows:
        last = _parse(row["last_checked"])
        if last is None or at - last >= EVERY * min(2 ** int(row["fail_count"]), MAX_BACKOFF):
            out.append(row)
    return out[:PER_SWEEP]


def sweep(db: storage.Store, fetch: Callable[[str], str], push: Callable[..., bool], *, at: datetime | None = None,
          pause: Callable[[float], None] = time.sleep, ntfy_base: str = "") -> dict:
    """Read every watch that is due. Returns `{read, failed, alerts}`."""
    at = at or storage.now()
    with db.connect() as conn:
        owner = conn.execute("SELECT topic FROM owner").fetchone()
    topic = owner["topic"] if owner else ""
    read = failed = alerts = 0
    last_host_at: dict[str, float] = {}
    for watch in due(db, at):
        url = db.unseal(watch["url_sealed"])
        host = watch["host"] or urlsplit(url).hostname or ""
        if host in last_host_at:
            gap = HOST_PAUSE_S - (time.monotonic() - last_host_at[host])
            if gap > 0:
                pause(gap)
        try:
            offer = pricewatch.read_markup(fetch(url)) if url else {}
        except Exception:  # noqa: BLE001 - one page's failure is that page's, not every watch's
            offer = {}
        last_host_at[host] = time.monotonic()
        if not offer:
            failed += 1
            with db.connect() as conn:
                conn.execute("UPDATE watches SET last_checked = ?, fail_count = fail_count + 1, last_error = ?"
                             " WHERE watch_id = ?", (storage.stamp(at), "no price could be read", watch["watch_id"]))
            continue
        read += 1
        with db.connect() as conn:
            conn.execute("UPDATE watches SET last_checked = ?, last_price = ?, last_error = '', fail_count = 0"
                         " WHERE watch_id = ?", (storage.stamp(at), offer["price"], watch["watch_id"]))
        if watch["currency"] and offer.get("currency") and watch["currency"] != offer["currency"]:
            continue
        kind = pricewatch.crossed(offer["price"], target=watch["target"], drop_pct=watch["drop_pct"],
                                  started_price=watch["started_price"])
        if not kind or not pricewatch.worth_repeating(
                offer["price"], watch["last_alert_price"], _parse(watch["last_alert_at"]), at):
            continue
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO alerts (watch_id, kind, label, price, was_price, currency, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (watch["watch_id"], kind, watch["label"], offer["price"], watch["started_price"],
                 offer.get("currency") or watch["currency"], storage.stamp(at)))
            conn.execute("UPDATE watches SET last_alert_price = ?, last_alert_at = ? WHERE watch_id = ?",
                         (offer["price"], storage.stamp(at), watch["watch_id"]))
        alerts += 1
        price = f"{offer['price']:g} {offer.get('currency') or watch['currency']}".strip()
        # No link: a push service is a third party, and the address stays with the relay.
        push(ntfy_base, topic, "Price dropped", f"{watch['label'] or 'A page you watch'}: {price}")
    return {"read": read, "failed": failed, "alerts": alerts}
