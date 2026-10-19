"""What a page cost before, and whether it is worth waiting.

A listing says what it costs now and, often, what it "used to" cost. Neither
number is evidence: the second is the seller's. The only honest reference is
what the same page has said on the days the reader looked, and nobody else has
that, so Kriko keeps it.

* **Memory.** Every product page the reader reads adds a price point (one per
  product per few hours, or sooner if the price moved). Nothing is fetched to
  do it: the extension already read the page.
* **Judgement.** `assess` compares today's price to that memory and says one
  plain thing: first sighting, lowest seen, the usual price, or high; and, where
  the page claims a discount, whether the memory supports the claim. It says "I
  have only watched since …" before it says anything it cannot back.
* **Watching.** A watch re-reads the page itself, a few times a day, and
  raises an alert only when the price crosses what the reader asked for. A shop
  that renders its price with script cannot be re-read this way; that is
  recorded on the watch ("could not read the price") and the page is still
  checked whenever the reader opens it.

The price is always the page's own figure in the page's own currency. Nothing
here converts, averages across currencies or invents a number.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import statistics
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, unquote_plus, urlsplit

from app import htmlscan

#: A product page is remembered once per this long unless the price moved.
SAME_PRICE_WINDOW = timedelta(hours=6)
#: Price points older than this are of no use to a judgement and are dropped.
KEEP_DAYS = 400
#: The window a judgement looks back over.
LOOK_BACK_DAYS = 90
#: What makes a history long enough to judge by: sightings, and days they span.
MIN_POINTS, MIN_SPAN_DAYS = 3, 7
#: A claimed discount is judged against a longer memory.
DISCOUNT_SPAN_DAYS = 14
#: A watch is re-read this often, at most.
SWEEP_EVERY = timedelta(hours=6)
MAX_WATCHES = 60
#: Sightings kept for one page. A year of daily visits is 365; this is a bound, not a target.
MAX_POINTS_PER_PAGE = 300
#: One alert per watch per price: a lower price speaks again, the same one does not.
REALERT_AFTER = timedelta(days=14)

#: Query parameters that name the product rather than the visit.
_IDENTITY_PARAMS = {"id", "sku", "pid", "product", "productid", "product_id", "item",
                    "itemid", "variant", "v", "p", "asin", "model", "mpn", "gtin", "ean"}

#: Query parameters that follow the reader around rather than name the page.
_TRACKING = re.compile(r"^(?:utm_.*|gclid|fbclid|msclkid|yclid|dclid|mc_cid|mc_eid|igshid|"
                       r"ref|ref_.*|_hsenc|_hsmi|spm|scid|cmpid|campaign.*)$", re.I)

_CURRENCY_SIGNS = {"₺": "TRY", "tl": "TRY", "€": "EUR", "$": "USD", "£": "GBP", "¥": "JPY",
                   "₹": "INR", "₽": "RUB", "zł": "PLN", "kr": "SEK"}


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _parse_stamp(text: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


# ── identity of a page ──────────────────────────────────────────────────


def product_key(url: str) -> str:
    """A stable name for one product page: host, path and the query that names the product."""
    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parts.path.lower()) or "/"
    query = sorted((key.lower(), value) for key, value in parse_qsl(parts.query)
                   if key.lower() in _IDENTITY_PARAMS)
    tail = "?" + "&".join(f"{key}={value}" for key, value in query) if query else ""
    return f"{host}{path}{tail}"[:400]


def strip_tracking(url: str) -> str:
    """The address without what a campaign or an ad click added to it."""
    parts = urlsplit(str(url or "").strip())
    # The query is kept as written: decoding and rejoining turns `%26` into a
    # second parameter, `%23` into a fragment and `+` into a space, and the stored
    # address is the one a watch reads again.
    kept = [piece for piece in parts.query.split("&")
            if piece and not _TRACKING.match(unquote_plus(piece.partition("=")[0]))]
    return parts._replace(query="&".join(kept), fragment="").geturl()


def host_of(url: str) -> str:
    return (urlsplit(str(url or "")).hostname or "").lower().removeprefix("www.")


# ── reading a price ─────────────────────────────────────────────────────


def parse_amount(text) -> float | None:
    """A number out of whatever the page printed: `1.299,90 TL`, `$1,299.90`, `1299.9`."""
    if isinstance(text, bool) or text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    # One number, or nothing. Gluing the digits of "from 10 to 30" into 1030, or of
    # "-50% 199,90 TL" into 50199.9, reports a price the page never showed; a
    # percentage is a discount, not a price, and two amounts are a range.
    shown = re.sub(r"\d[\d.,]*\s*%|%\s*\d[\d.,]*", " ", str(text))
    numbers = re.findall(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?(?!\d)|\d[\d.,]*", shown)
    if len(numbers) != 1:
        return None
    cleaned = re.sub(r"[^\d.,]", "", numbers[0]).strip(".,")
    if not cleaned or not re.search(r"\d", cleaned):
        return None
    if "," in cleaned and "." in cleaned:
        decimal = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        cleaned = cleaned.replace(thousands, "").replace(decimal, ".")
    elif "," in cleaned or "." in cleaned:
        sign = "," if "," in cleaned else "."
        pieces = cleaned.split(sign)
        grouped = len(pieces) > 2 or (len(pieces[-1]) == 3 and 0 < len(pieces[0]) <= 3)
        cleaned = "".join(pieces) if grouped else ".".join(pieces)
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if 0 < value < 1e10 else None


def _currency(text) -> str:
    text = str(text or "").strip()
    if re.fullmatch(r"[A-Za-z]{3}", text):
        return text.upper()
    return _CURRENCY_SIGNS.get(text.lower(), "")


def extract(fields: dict | None) -> dict:
    """The offer a scrape carries, or `{}` when the page showed no price.

    `fields` is what the extension read (`ld:*` keys are the page's structured
    data; `shown:*` the price text it found beside the title, for a shop that
    publishes none). A range ("from 10 to 30") has no single price, so only a
    `price` or a `lowPrice` counts, and a range is never reported as a price.
    """
    fields = fields if isinstance(fields, dict) else {}
    price = parse_amount(fields.get("ld:price"))
    if price is None:
        price = parse_amount(fields.get("ld:lowPrice"))
    if price is None:
        price = parse_amount(fields.get("shown:price"))
    if price is None:
        return {}
    was = parse_amount(fields.get("ld:listPrice")) or parse_amount(fields.get("shown:was"))
    if was is not None and was <= price:
        was = None
    stock = str(fields.get("ld:availability") or "").casefold()
    in_stock: bool | None = None
    if stock:
        in_stock = not any(word in stock for word in ("outofstock", "soldout", "discontinued"))
    return {
        "price": price, "was_price": was,
        "currency": _currency(fields.get("ld:priceCurrency")) or _currency(fields.get("shown:currency")),
        "seller": str(fields.get("ld:seller") or "")[:120],
        "in_stock": in_stock,
    }


_LD_TYPE = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"']", re.I)
_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")


def _walk(root):
    """Every object in a JSON document, without recursion: a page chooses how deep it nests."""
    todo = [root]
    while todo:
        node = todo.pop()
        if isinstance(node, dict):
            yield node
            todo.extend(node.values())
        elif isinstance(node, list):
            todo.extend(node)


def read_markup(markup: str) -> dict:
    """The offer a fetched page publishes for search engines, as `extract` reads a scrape."""
    fields: dict[str, str] = {}
    for block in htmlscan.inner_texts(markup or "", ("script",), want=lambda tag: bool(_LD_TYPE.match(tag))):
        try:
            data = json.loads(block.strip())
        except (ValueError, RecursionError):
            # One page's hostile JSON must not end the sweep: it fails alone.
            continue
        for node in _walk(data):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "Offer" in kinds or "AggregateOffer" in kinds or "offers" in node:
                offers = node.get("offers", node)
                for offer in offers if isinstance(offers, list) else [offers]:
                    if not isinstance(offer, dict):
                        continue
                    for target, source in (("ld:price", "price"), ("ld:lowPrice", "lowPrice"),
                                           ("ld:priceCurrency", "priceCurrency"),
                                           ("ld:availability", "availability")):
                        if source in offer and target not in fields:
                            fields[target] = str(offer[source])
                    spec = offer.get("priceSpecification")
                    for one in spec if isinstance(spec, list) else [spec]:
                        if isinstance(one, dict) and re.search(
                                r"list|strike|msrp|original", str(one.get("priceType", "")), re.I):
                            fields.setdefault("ld:listPrice", str(one.get("price", "")))
                    seller = offer.get("seller")
                    if isinstance(seller, dict):
                        seller = seller.get("name")
                    if seller and "ld:seller" not in fields:
                        fields["ld:seller"] = str(seller)
    if "ld:price" not in fields:
        for tag in _META.findall(markup or ""):
            attrs = {key.lower(): first or second for key, first, second in _ATTR.findall(tag)}
            name = (attrs.get("property") or attrs.get("name") or "").lower()
            if name in ("product:price:amount", "og:price:amount"):
                fields.setdefault("ld:price", attrs.get("content", ""))
            elif name in ("product:price:currency", "og:price:currency"):
                fields.setdefault("ld:priceCurrency", attrs.get("content", ""))
    return extract(fields)


# ── memory ───────────────────────────────────────────────────────────────


def observe(conn: sqlite3.Connection, url: str, name: str, fields: dict | None, *,
            source: str = "visit", now: datetime | None = None) -> dict | None:
    """Remember the price this page shows. Returns the offer, or `None` when it shows none."""
    offer = extract(fields)
    if not offer or not str(url or "").startswith(("http://", "https://")):
        return None
    return record(conn, url, name, offer, source=source, now=now)


def record(conn: sqlite3.Connection, url: str, name: str, offer: dict, *,
           source: str = "visit", now: datetime | None = None) -> dict:
    now = now or _now()
    key = product_key(url)
    last = conn.execute(
        "SELECT price, currency, seen_at FROM price_points WHERE product_key = ?"
        " ORDER BY seen_at DESC, point_id DESC LIMIT 1", (key,)).fetchone()
    seen = _parse_stamp(last["seen_at"]) if last else None
    unchanged = bool(last and abs(last["price"] - offer["price"]) < 0.005
                     and last["currency"] == (offer.get("currency") or "")
                     and seen and now - seen < SAME_PRICE_WINDOW)
    if not unchanged:
        conn.execute(
            "INSERT INTO price_points (product_key, url, host, name, seller, price, was_price,"
            " currency, in_stock, seen_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, strip_tracking(url)[:2000], host_of(url), str(name or "")[:300], offer.get("seller", ""),
             offer["price"], offer.get("was_price"), offer.get("currency") or "",
             None if offer.get("in_stock") is None else int(offer["in_stock"]),
             _stamp(now), source))
        conn.execute("DELETE FROM price_points WHERE seen_at < ?",
                     (_stamp(now - timedelta(days=KEEP_DAYS)),))
        # A page that changes its price on every load must not fill the file.
        conn.execute(
            "DELETE FROM price_points WHERE product_key = ? AND point_id NOT IN ("
            "SELECT point_id FROM price_points WHERE product_key = ? ORDER BY seen_at DESC,"
            " point_id DESC LIMIT ?)", (key, key, MAX_POINTS_PER_PAGE))
    # Even an unchanged price is a check: the watch records when it last looked.
    _check_watch(conn, key, offer, now)
    conn.commit()
    return offer


def history(conn: sqlite3.Connection, key: str, *, days: int = LOOK_BACK_DAYS,
            currency: str = "", now: datetime | None = None) -> list[dict]:
    since = _stamp((now or _now()) - timedelta(days=days))
    rows = conn.execute(
        "SELECT price, was_price, currency, seen_at, seller, in_stock FROM price_points"
        " WHERE product_key = ? AND seen_at >= ? ORDER BY seen_at, point_id", (key, since))
    return [dict(row) for row in rows if not currency or not row["currency"]
            or row["currency"] == currency]


def assess(points: list[dict], price: float, *, was_price: float | None = None,
           now: datetime | None = None) -> dict:
    """One plain judgement of `price` against what these pages have said before.

    `points` are earlier sightings of the same page and currency, oldest first
    and not including the price being judged. Returns:

    * `verdict`: `first`, `lowest`, `usual`, `high` or `thin` (seen, but not
      enough to judge by);
    * `discount`: `None` when the page claims no discount, else `real`,
      `inflated`, `usual_price` or `unknown`, with the page's claimed percentage;
    * `summary` and `discount_summary`: the sentences to show.

    Kriko says "not enough history" before it says anything it cannot support:
    three sightings over a week, and two weeks to judge a claimed discount.
    """
    now = now or _now()
    prices = [one["price"] for one in points]
    stamps = [stamp for stamp in (_parse_stamp(one["seen_at"]) for one in points) if stamp]
    span_days = (max(stamps) - min(stamps)).days if len(stamps) > 1 else 0
    first_seen = min(stamps) if stamps else None
    out: dict = {
        "count": len(points), "span_days": span_days,
        "first_seen": _stamp(first_seen) if first_seen else "",
        "low": min(prices) if prices else None, "high": max(prices) if prices else None,
        "median": statistics.median(prices) if prices else None,
        "verdict": "first", "summary": "", "discount": None, "discount_summary": "",
        "claimed_pct": None,
    }
    if not points:
        out["summary"] = "First time Kriko has seen this price. It will remember it from here."
    elif len(points) < MIN_POINTS or span_days < MIN_SPAN_DAYS:
        out["verdict"] = "thin"
        since = first_seen.date().isoformat() if first_seen else ""
        out["summary"] = (f"Kriko has only watched this page since {since} "
                          f"({len(points)} sighting{'s' if len(points) != 1 else ''}); "
                          "too little to say if the price is good.")
    else:
        low, median = min(prices + [price]), statistics.median(prices)
        # A price that never moved is not "the lowest": it is the price.
        if price <= low * 1.005 and max(prices) > low * 1.02:
            out["verdict"] = "lowest"
            out["summary"] = f"The lowest Kriko has seen in {span_days} days."
        elif price >= median * 1.10:
            out["verdict"] = "high"
            out["summary"] = (f"About {round((price / median - 1) * 100)}% above its usual price "
                              f"over the last {span_days} days. Waiting is reasonable.")
        else:
            out["verdict"] = "usual"
            out["summary"] = f"Close to its usual price over the last {span_days} days."
    if was_price and was_price > price:
        claimed = round((1 - price / was_price) * 100)
        out["claimed_pct"] = claimed
        if len(points) >= MIN_POINTS and span_days >= DISCOUNT_SPAN_DAYS:
            seen_high = max(prices)
            median = statistics.median(prices)
            if seen_high < was_price * 0.9:
                out["discount"] = "inflated"
                out["discount_summary"] = (
                    f"The page claims {claimed}% off {was_price:g}, but in {span_days} days "
                    f"Kriko never saw it above {seen_high:g}. The old price looks invented.")
            elif claimed >= 10 and price >= median * 0.97:
                out["discount"] = "usual_price"
                out["discount_summary"] = (
                    f"The page claims {claimed}% off, but {price:g} is what this costs most "
                    "days. It is the normal price, not a sale.")
            else:
                out["discount"] = "real"
                out["discount_summary"] = (
                    f"The {claimed}% discount holds up against what Kriko saw: it was higher "
                    "recently.")
        else:
            out["discount"] = "unknown"
            out["discount_summary"] = (
                f"The page claims {claimed}% off. Kriko cannot check that yet: "
                f"it needs about {DISCOUNT_SPAN_DAYS} days of history for this page.")
    return out


def judge(conn: sqlite3.Connection, url: str, offer: dict, *, now: datetime | None = None) -> dict:
    """`assess` for a page just observed: its earlier sightings, not counting this one."""
    now = now or _now()
    key = product_key(url)
    rows = history(conn, key, currency=offer.get("currency") or "", now=now)
    # The sighting recorded a moment ago is the page's current price, not its past.
    # An equal price from earlier is a past sighting: `record` skips a repeat inside
    # a few hours, so the newest row is not always this visit.
    if rows and abs(rows[-1]["price"] - offer["price"]) < 0.005:
        taken = _parse_stamp(rows[-1]["seen_at"])
        if taken and now - taken < timedelta(minutes=1):
            rows = rows[:-1]
    result = assess(rows, offer["price"], was_price=offer.get("was_price"), now=now)
    result.update(price=offer["price"], was_price=offer.get("was_price"),
                  currency=offer.get("currency") or "", product_key=key)
    return result


def series(conn: sqlite3.Connection, url: str, *, days: int = 180) -> list[dict]:
    """The price over time for a drawn line: one point per sighting."""
    return [{"price": one["price"], "at": one["seen_at"], "currency": one["currency"]}
            for one in history(conn, product_key(url), days=days)]


# ── same product elsewhere ───────────────────────────────────────────────


def _tokens(name: str) -> set[str]:
    return {token for token in re.sub(r"[^\w]+", " ", str(name or "").casefold()).split()
            if len(token) > 1}


def same_product(a: str, b: str) -> bool:
    """Whether two listing names are one product: every model-like token agrees.

    A token with a digit in it ("a2338", "wh-1000xm5", "256gb") is a model or
    a variant, and two names that disagree on one are two products. Names with
    no such token are never matched: a cheaper "blue shirt" is not evidence.
    """
    one, two = _tokens(a), _tokens(b)
    model = {token for token in one | two if re.search(r"\d", token) and re.search(r"[a-z]", token)
             or re.search(r"\d{3,}", token)}
    if not model:
        return False
    if any((token in one) != (token in two) for token in model):
        return False
    return len(one & two) / max(1, len(one | two)) >= 0.5


def elsewhere(conn: sqlite3.Connection, name: str, url: str, currency: str, *,
              now: datetime | None = None, days: int = 30) -> list[dict]:
    """Other pages Kriko saw this product on, newest sighting each, cheapest first."""
    if not currency:
        return []  # a price with no currency cannot be set against one that has it
    key = product_key(url)
    own_host = host_of(url)
    since = _stamp((now or _now()) - timedelta(days=days))
    seen: dict[str, dict] = {}
    for row in conn.execute(
            "SELECT product_key, url, host, name, seller, price, currency, seen_at, in_stock"
            " FROM price_points WHERE seen_at >= ? AND product_key != ? ORDER BY seen_at DESC LIMIT 2000",
            (since, key)):
        if row["product_key"] in seen or row["host"] == own_host:
            continue
        if currency and row["currency"] and row["currency"] != currency:
            continue
        if row["in_stock"] == 0 or not same_product(name, row["name"]):
            continue
        seen[row["product_key"]] = dict(row)
    return sorted(seen.values(), key=lambda one: one["price"])


# ── watches ──────────────────────────────────────────────────────────────


def _watch(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def watch_for(conn: sqlite3.Connection, url: str) -> dict | None:
    row = conn.execute("SELECT * FROM watches WHERE product_key = ?", (product_key(url),)).fetchone()
    return _watch(row) if row else None


def watches(conn: sqlite3.Connection) -> list[dict]:
    return [_watch(row) for row in conn.execute("SELECT * FROM watches ORDER BY created_at DESC")]


def watch(conn: sqlite3.Connection, url: str, name: str = "", *, target=None, drop_pct=None,
          price=None, currency: str = "", cloud: bool | None = None, now: datetime | None = None) -> dict:
    """Keep an eye on this page. A second call on the same page changes the terms."""
    if not str(url or "").startswith(("http://", "https://")):
        raise ValueError("a watch needs the page's address")
    target, drop_pct = parse_amount(target), parse_amount(drop_pct)
    if drop_pct is not None and not 0 < drop_pct < 100:
        raise ValueError("a fall is a percentage between 0 and 100")
    key = product_key(url)
    now = now or _now()
    existing = conn.execute("SELECT * FROM watches WHERE product_key = ?", (key,)).fetchone()
    start = parse_amount(price)
    if start is None:
        last = conn.execute("SELECT price FROM price_points WHERE product_key = ?"
                            " ORDER BY seen_at DESC, point_id DESC LIMIT 1", (key,)).fetchone()
        start = last["price"] if last else None
    if existing:
        conn.execute("UPDATE watches SET target = ?, drop_pct = ?, name = COALESCE(NULLIF(?, ''), name),"
                     " updated_at = ?, cloud = COALESCE(?, cloud) WHERE watch_id = ?",
                     (target, drop_pct, str(name)[:300], _stamp(now),
                      None if cloud is None else int(cloud), existing["watch_id"]))
        watch_id = existing["watch_id"]
    else:
        count = conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
        if count >= MAX_WATCHES:
            raise OverflowError(f"{MAX_WATCHES} pages are already watched; stop one first")
        watch_id = secrets.token_hex(8)
        conn.execute(
            "INSERT INTO watches (watch_id, product_key, url, name, currency, target, drop_pct,"
            " started_price, created_at, cloud, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (watch_id, key, strip_tracking(url)[:2000], str(name or "")[:300], _currency(currency), target, drop_pct,
             start, _stamp(now), int(bool(cloud)), _stamp(now)))
    conn.commit()
    return _watch(conn.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone())


def unwatch(conn: sqlite3.Connection, watch_id: str, *, remember: bool = True) -> bool:
    row = conn.execute("SELECT product_key FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
    cursor = conn.execute("DELETE FROM watches WHERE watch_id = ?", (watch_id,))
    conn.commit()
    if cursor.rowcount and row and remember:
        from app import cloud  # noqa: PLC0415 - cloud reads this module

        cloud.note_deleted(conn, "watch", row["product_key"])
    return bool(cursor.rowcount)


def set_cloud(conn: sqlite3.Connection, watch_id: str, on: bool, *, now: datetime | None = None) -> dict | None:
    """Turn the relay's watching of this page on or off. The relay learns the page only when this is on."""
    cursor = conn.execute("UPDATE watches SET cloud = ?, updated_at = ? WHERE watch_id = ?",
                          (int(on), _stamp(now or _now()), watch_id))
    conn.commit()
    if not cursor.rowcount:
        return None
    return _watch(conn.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone())


def adopt(conn: sqlite3.Connection, row: dict) -> None:
    """Keep a watch that came from another device, keeping what it measured here (price, last read)."""
    key = row["product_key"]
    have = conn.execute("SELECT updated_at FROM watches WHERE product_key = ?", (key,)).fetchone()
    if have and have["updated_at"] >= row["updated_at"]:
        return
    made = watch(conn, row["url"], row["name"], target=row["target"], drop_pct=row["drop_pct"],
                 price=row["started_price"], currency=row["currency"] or "", cloud=bool(row["cloud"]))
    conn.execute("UPDATE watches SET updated_at = ? WHERE watch_id = ?", (row["updated_at"], made["watch_id"]))
    conn.commit()


def crossed(price: float, *, target: float | None, drop_pct: float | None,
            started_price: float | None) -> str:
    """Whether `price` is what a watch asked to be told about: `target`, `drop`, or `""`.

    One rule for every place a watch is read (the desktop, and the relay that
    watches while the computer is off), so the two can never disagree about
    what a reader asked for.
    """
    if target is not None and price <= target:
        return "target"
    if drop_pct and started_price and price <= started_price * (1 - drop_pct / 100):
        return "drop"
    return ""


def worth_repeating(price: float, last_price: float | None, last_at: datetime | None,
                    now: datetime) -> bool:
    """Whether a second alert for the same watch is news: only a lower price, or a long wait."""
    if last_price is None or last_at is None:
        return True
    return not (price >= last_price and now - last_at < REALERT_AFTER)


def _alert(conn: sqlite3.Connection, row: sqlite3.Row, kind: str, offer: dict,
           now: datetime) -> bool:
    last = conn.execute(
        "SELECT price, created_at FROM watch_alerts WHERE watch_id = ? ORDER BY created_at DESC"
        " LIMIT 1", (row["watch_id"],)).fetchone()
    if last and not worth_repeating(offer["price"], last["price"],
                                    _parse_stamp(last["created_at"]), now):
        return False
    conn.execute(
        "INSERT INTO watch_alerts (alert_id, watch_id, kind, name, url, price, was_price,"
        " currency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (secrets.token_hex(8), row["watch_id"], kind, row["name"], row["url"], offer["price"],
         row["started_price"], offer.get("currency") or row["currency"], _stamp(now)))
    return True


def _check_watch(conn: sqlite3.Connection, key: str, offer: dict, now: datetime) -> None:
    row = conn.execute("SELECT * FROM watches WHERE product_key = ?", (key,)).fetchone()
    if not row:
        return
    if row["currency"] and offer.get("currency") and row["currency"] != offer["currency"]:
        return
    conn.execute("UPDATE watches SET last_checked = ?, last_price = ?, last_error = '',"
                 " currency = COALESCE(NULLIF(currency, ''), ?) WHERE watch_id = ?",
                 (_stamp(now), offer["price"], offer.get("currency") or "", row["watch_id"]))
    kind = crossed(offer["price"], target=row["target"], drop_pct=row["drop_pct"],
                   started_price=row["started_price"])
    if kind:
        _alert(conn, row, kind, offer, now)


def alerts(conn: sqlite3.Connection, *, unread_only: bool = True, limit: int = 50) -> list[dict]:
    where = "WHERE read_at = ''" if unread_only else ""
    rows = conn.execute(
        f"SELECT * FROM watch_alerts {where} ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in rows]


def read_alerts(conn: sqlite3.Connection, alert_ids: list[str] | None = None, *,
                now: datetime | None = None) -> int:
    stamp = _stamp(now or _now())
    if alert_ids:
        marks = ",".join("?" * len(alert_ids))
        cursor = conn.execute(
            f"UPDATE watch_alerts SET read_at = ? WHERE read_at = '' AND alert_id IN ({marks})",
            (stamp, *alert_ids))
    else:
        cursor = conn.execute("UPDATE watch_alerts SET read_at = ? WHERE read_at = ''", (stamp,))
    conn.commit()
    return cursor.rowcount


def due(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    """Watches not read in `SWEEP_EVERY`."""
    cutoff = _stamp((now or _now()) - SWEEP_EVERY)
    rows = conn.execute("SELECT * FROM watches WHERE last_checked = '' OR last_checked <= ?"
                        " ORDER BY last_checked", (cutoff,))
    return [_watch(row) for row in rows]


def _read_or_nothing(markup: str) -> dict:
    """`read_markup`, where whatever a page did to it is that page's failure and nobody else's."""
    try:
        return read_markup(markup) if markup else {}
    except Exception:  # noqa: BLE001 - one bad page must not stop the rest
        return {}


def sweep(conn: sqlite3.Connection, fetch: Callable[[str], str], *,
          now: datetime | None = None, pause: Callable[[], None] | None = None) -> dict:
    """Re-read every watch that is due. `fetch(url)` returns the page's markup, or "".

    A page that cannot be read, or shows no price in its own markup, is
    recorded on the watch and left alone: the next visit by the reader still
    updates it. Nothing here retries within a sweep.
    """
    now = now or _now()
    checked = failed = alerted = 0
    for one in due(conn, now):
        if pause is not None and checked + failed:
            pause()
        try:
            markup = fetch(one["url"])
        except Exception as error:  # noqa: BLE001 - one bad page must not stop the rest
            markup, why = "", f"could not be fetched ({type(error).__name__})"
        else:
            why = "could not be fetched" if not markup else ""
        offer = _read_or_nothing(markup)
        if not offer and not why:
            why = "the page does not publish its price in a way Kriko can read without a browser"
        if why:
            conn.execute("UPDATE watches SET last_checked = ?, last_error = ? WHERE watch_id = ?",
                         (_stamp(now), why, one["watch_id"]))
            conn.commit()
            failed += 1
            continue
        before = conn.execute("SELECT COUNT(*) FROM watch_alerts").fetchone()[0]
        record(conn, one["url"], one["name"], offer, source="watch", now=now)
        alerted += conn.execute("SELECT COUNT(*) FROM watch_alerts").fetchone()[0] - before
        checked += 1
    return {"checked": checked, "failed": failed, "alerts": alerted}
