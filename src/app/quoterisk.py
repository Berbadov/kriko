"""How much stands behind a vendor quote, and why.

A quote is typed by the reader (or read from a page the extension already
saw). It carries a URL and a handful of terms; the site tier comes from
`sellers.json` through `exactfind.classify`, the same data every buying answer
uses. This module is a pure function of that quote: no network, no model, and
no invented signals.

The rule the answer and the screen both follow: a level always comes with the
sentences behind it, and "unknown" is never shown as "trusted". A marketplace
is judged by its seller, not by the site; a classified listing is a stranger
until something proves otherwise.
"""

from __future__ import annotations

from datetime import date

from app import exactfind

#: Levels in the order a screen may show them. `unknown` is deliberately not
#: green: a site Kriko does not know has not earned a favourable mark.
LEVELS = ("red", "amber", "green", "unknown")

#: A quote whose validity has passed is worth re-asking, not discarding.
STALE_AFTER_DAYS = 30


def _level_of_rank(rank: int) -> str:
    if rank >= 3:
        return "red"
    if rank:
        return "amber"
    return "green"


def quote_risk(quote: dict, *, today: date | None = None) -> dict:
    """The seller and terms risk of one quote: `{level, reasons, site}`.

    `quote` reads `url`, `seller`, `delivery_days`, `warranty_months`,
    `valid_until` and `quote_date`. Missing fields are "not stated", never a
    guessed value. `today` makes the expiry check testable.
    """
    quote = quote if isinstance(quote, dict) else {}
    url = str(quote.get("url") or "").strip()
    seller = " ".join(str(quote.get("seller") or "").split())
    reasons: list[str] = []

    if not url:
        return {
            "level": "unknown",
            "reasons": ["no page to check: nothing here vouches for the seller"],
            "site": None,
        }

    site = exactfind.classify(url)
    tier = site["tier"]
    rank = 0

    if tier in ("classified", "unknown"):
        if tier == "unknown":
            return {
                "level": "unknown",
                "reasons": [f"{site['label']}: not a site Kriko knows, so nothing here vouches for the seller"],
                "site": site,
            }
        rank = max(rank, 3)
        reasons.append(f"{site['label']}: nobody vouches for this seller")
    elif tier == "marketplace":
        rank = max(rank, 1)
        reasons.append("a marketplace listing: the site is only as good as the seller on the page")
        if not seller:
            reasons.append("the seller is not named on the quote")
        else:
            reasons.append(f"the quote names {seller}; Kriko has not checked it")
    elif tier == "comparison":
        rank = max(rank, 1)
        reasons.append("a comparison site: open the shop it links to and judge that shop")
    else:
        reasons.append(f"{site['label']} ({site['domain']})")

    if not seller and tier not in ("marketplace", "comparison"):
        reasons.append("no seller named")

    delivery = _int(quote.get("delivery_days"))
    if delivery is not None and delivery > 60:
        rank = max(rank, 1)
        reasons.append(f"delivery quoted at {delivery} days")

    warranty = _int(quote.get("warranty_months"))
    if warranty == 0:
        rank = max(rank, 1)
        reasons.append("no warranty stated")

    stated = str(quote.get("valid_until") or "").strip()
    if stated:
        when = _date(stated)
        now = today or date.today()
        if when is None:
            reasons.append(f"validity {stated!r} is not a date Kriko can read")
        elif when < now:
            rank = max(rank, 1)
            reasons.append(f"the quote expired on {stated}")

    return {"level": _level_of_rank(rank), "reasons": reasons, "site": site}


def rank_quotes(quotes: list[dict], *, estimate_currency: str, rates: dict,
                today: date | None = None) -> list[dict]:
    """Quotes in landed-cost order, cheapest first, with the reasons behind it.

    Landed cost here is the gross unit price converted to the estimate's
    currency at the stated rate plus nothing else: delivery *days* and warranty
    *months* are terms, not money, and this module will not invent a delivery
    charge. A quote whose currency has no rate is not ranked (it would be a
    comparison of unlike numbers) and says why. Ties break on a shorter
    delivery, because that is the only other term measured in a comparable
    unit.
    """
    out: list[dict] = []
    for quote in quotes if isinstance(quotes, list) else []:
        row = dict(quote)
        risk = quote_risk(row, today=today)
        price = _float(row.get("unit_price"))
        currency = str(row.get("currency") or estimate_currency).upper()
        rate = _rate(currency, estimate_currency, rates)
        row["risk"] = risk
        if price is None:
            row["landed"] = None
            row["rank_reasons"] = ["no price on this quote"]
        elif rate is None:
            row["landed"] = None
            row["rank_reasons"] = [f"no {currency} to {estimate_currency} rate, so it cannot be compared"]
        else:
            vat = _float(row.get("vat_rate")) or 0.0
            gross = price if row.get("vat_included") else price * (1 + vat / 100)
            row["landed"] = round(gross * rate, 4)
            row["rank_reasons"] = [
                f"{gross:.2f} {currency} gross at 1 {currency} = {rate:g} {estimate_currency}"
            ]
            delivery = _int(row.get("delivery_days"))
            if delivery is not None:
                row["rank_reasons"].append(f"delivery {delivery} days")
            row["rank_reasons"].extend(risk["reasons"][:1])
        out.append(row)

    ranked = sorted(
        out,
        key=lambda row: (
            row["landed"] is None,
            row["landed"] if row["landed"] is not None else 0.0,
            _int(row.get("delivery_days")) if _int(row.get("delivery_days")) is not None else 10**6,
            str(row.get("vendor") or ""),
            str(row.get("quote_id") or ""),
        ),
    )
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position if row["landed"] is not None else None
    return ranked


def _rate(currency: str, estimate_currency: str, rates: dict) -> float | None:
    """Estimate-currency units per one quote-currency unit, from TRY rates.

    `rates` maps a currency to how many TRY one unit is worth (TCMB's own
    direction). TRY is 1. A rate the reader has not entered is absent, never
    guessed.
    """
    rates = rates if isinstance(rates, dict) else {}
    source = _float(rates.get(currency))
    target = _float(rates.get(estimate_currency))
    if source is None or target in (None, 0):
        return None
    return source / target


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _int(value) -> int | None:
    number = _float(value)
    return None if number is None else int(number)


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
