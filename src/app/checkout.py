"""The last look before paying.

Advice is cheapest to follow on a product page and most valuable on the page
where the card comes out. By then the reader has stopped researching and is
about to spend, so this is the one place Kriko speaks up without being asked.
It says only what it can show:

* **Is it the thing you researched?** A cart line that shares a family name with
  something the reader saved, queued or was told to pick, but differs on a model
  or size token, is the classic wrong-variant mistake.
* **Is it cheaper elsewhere?** The same product (`pricewatch.same_product`) on
  another shop Kriko saw in the last month, in the same currency, in stock.
* **Is today a good price for this page?** `pricewatch.judge` against what the
  page said before, including whether a claimed discount holds.
* **Who is taking the money?** The shop's tier and any payment method scams use.
* **Can it go back?** Whether the page shows return terms at all. A page that
  shows none is "check", never "no returns".

The verdict is `go`, `check` or `stop`, and every finding says why in a
sentence. `stop` is reserved for what is plainly wrong (a scam payment method, a
different product in the cart); everything else is `check`. Kriko never blocks
the reader: the panel is advice on a page the reader still owns.

Pure given the app state: items come from the page (best effort), and when the
page yields none the reader's last product views on that host stand in, since
what is in a cart is usually what was just looked at.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta

from app import audit, pricewatch

#: A cart or payment page by what its address says; the extension adds what the
#: page shows. Words, not hosts: a closed vocabulary of how shops name this step.
CHECKOUT_PATH = re.compile(
    r"/(?:cart|basket|bag|checkout|payment|pay|order|sepet|sepetim|odeme|siparis|warenkorb|kasse|"
    r"panier|paiement|carrito|pagar|carrello|winkelwagen|zamowienie|koszyk)(?:/|\.|$|\?)", re.I)

_RETURNS = re.compile(
    r"return|refund|money[- ]back|iade|geri (?:odeme|gonder)|ruckgabe|widerruf|retour|remboursement|"
    r"devolucion|reso\b|terugsturen|zwrot", re.I)

#: How long a product view stands in for a cart line.
RECENT_VIEW = timedelta(hours=36)
MAX_ITEMS = 8


def is_checkout(url: str) -> bool:
    return bool(CHECKOUT_PATH.search(str(url or "")))


def _fold(text) -> str:
    return audit._fold(text)  # noqa: SLF001 - one folding rule for every comparison


def variant_clash(a: str, b: str) -> bool:
    """Same family of product, different model or size: the words overlap and the numbers differ.

    Only a token with a digit counts (a model, a size, a capacity). A different
    colour or an extra word is a variant the reader chose, not a mistake, so
    "Phone 128GB" against "Phone 256GB" clashes and "Phone blue" against
    "Phone black" does not.
    """
    one, two = pricewatch._tokens(a), pricewatch._tokens(b)  # noqa: SLF001
    words_one = {token for token in one if not re.search(r"\d", token)}
    words_two = {token for token in two if not re.search(r"\d", token)}
    shared = words_one & words_two
    if not shared or len(shared) / max(1, min(len(words_one), len(words_two))) < 0.5:
        return False
    numbers_one = {token for token in one if re.search(r"\d", token)}
    numbers_two = {token for token in two if re.search(r"\d", token)}
    return bool(numbers_one and numbers_two and numbers_one != numbers_two)


def _recent_views(conn: sqlite3.Connection, host: str, now: datetime) -> list[dict]:
    since = (now - RECENT_VIEW).isoformat(timespec="seconds")
    seen: dict[str, dict] = {}
    for row in conn.execute(
            "SELECT product_key, url, name, price, currency FROM price_points WHERE host = ?"
            " AND seen_at >= ? ORDER BY seen_at DESC", (host, since)):
        if row["product_key"] not in seen:
            seen[row["product_key"]] = {"name": row["name"], "price": row["price"],
                                        "currency": row["currency"], "url": row["url"]}
    return list(seen.values())[:MAX_ITEMS]


def _researched(conn: sqlite3.Connection) -> list[str]:
    """The names of what the reader saved, queued or was picked for them, newest first."""
    names = [row["label"] for row in conn.execute(
        "SELECT label FROM lookups ORDER BY created_at DESC LIMIT 40") if row["label"]]
    names += [row["name"] for row in conn.execute(
        "SELECT name FROM research_queue ORDER BY added_at DESC LIMIT 40") if row["name"]]
    names += [row["winner_name"] for row in conn.execute(
        "SELECT winner_name FROM picks ORDER BY created_at DESC LIMIT 10")]
    return names


def guard(conn: sqlite3.Connection, *, url: str, items: list[dict] | None = None, text: str = "",
          now: datetime | None = None) -> dict:
    """What to say at this checkout page: findings, a verdict, and the items they are about."""
    now = now or datetime.now(UTC)
    host = pricewatch.host_of(url)
    lines = [one for one in (items or []) if isinstance(one, dict) and str(one.get("name") or "").strip()]
    from_views = False
    if not lines:
        lines, from_views = _recent_views(conn, host, now), True
    lines = lines[:MAX_ITEMS]
    researched = _researched(conn)
    findings: list[dict] = []

    def add(severity: str, kind: str, message: str, item: str = "") -> None:
        findings.append({"severity": severity, "kind": kind, "message": message, "item": item})

    who = audit.seller(url, {}, text)
    if who["site"]["tier"] == "unknown" and who["level"] != "red":
        # Most small shops are unrecognised, and most are fine: say it, do not alarm.
        add("note", "seller", "Kriko does not know this shop yet. Look for reviews of the shop "
                              "itself before paying.")
    else:
        for note in who["notes"]:
            add("stop" if who["level"] == "red" else "check", "seller", note)

    for line in lines:
        name = str(line.get("name") or "")[:200]
        price = pricewatch.parse_amount(line.get("price"))
        currency = str(line.get("currency") or "").upper()
        clash = next((one for one in researched if variant_clash(name, one)), None)
        if clash and not any(pricewatch.same_product(name, one) for one in researched):
            # A recent view is a guess at the cart, not the cart: ask, do not stop.
            add("check" if from_views else "stop", "variant",
                f"You researched “{clash}”, but this is “{name}”. Check the model before paying.", name)
        if price is None:
            continue
        cheaper = [one for one in pricewatch.elsewhere(conn, name, line.get("url") or url, currency, now=now)
                   if one["price"] < price * 0.97]
        if cheaper:
            best = cheaper[0]
            add("check", "cheaper",
                f"Kriko saw {name} for {best['price']:g}{' ' + best['currency'] if best['currency'] else ''} "
                f"on {best['host']} (you pay {price:g}).", name)
        if line.get("url"):
            offer = {"price": price, "currency": currency, "was_price": None}
            verdict = pricewatch.judge(conn, line["url"], offer, now=now)
            if verdict["verdict"] == "high":
                add("check", "price", f"{name}: {verdict['summary']}", name)
            elif verdict["verdict"] == "lowest":
                add("ok", "price", f"{name}: {verdict['summary']}", name)

    if text and not _RETURNS.search(text):
        add("check", "returns", "This page shows no return terms. Find them before you pay.")
    elif text:
        add("ok", "returns", "The page mentions returns or refunds.")

    order = {"stop": 0, "check": 1, "note": 2, "ok": 3}
    findings.sort(key=lambda one: order[one["severity"]])
    overall = "stop" if any(one["severity"] == "stop" for one in findings) else \
        "check" if any(one["severity"] == "check" for one in findings) else "go"
    return {
        "verdict": overall, "findings": findings, "items": lines, "items_from": "recent views"
        if from_views else "the cart", "seller": who["level"],
        "headline": next((one["message"] for one in findings if one["severity"] in ("stop", "check")), ""),
    }
