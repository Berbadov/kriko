"""Choosing: the shortlist ranked for this reader, with a winner and what it costs to pick it.

A comparison table gives the reader columns and leaves the decision where it
was. A chat given the same columns gives a paragraph that ends "it depends on
your needs". Neither commits. This module does the part of deciding that code
can do honestly, from what Kriko already holds about each product:

* **fit** with what the reader said they need (`buyer.fit`);
* **known risks** from the packs, weighted by severity, halved when disputed;
* **price** against its own history and against the other candidates;
* **who sells it** and **how the page's claims and score hold up** (`audit`).

Each contributes a signed number *and the sentence that explains it*. The score
is only an order among these candidates for this reader, never a rating of a
product; the sentences are what is shown. The reader's own priorities scale the
terms they care about, so a reader who put durability at 5 sees the same
product lose more for a known failure than one who put it at 1.

`rank` returns a winner only when there are two or more candidates, and says
how clear the win is: `clear`, `close`, a `toss_up`, or `thin` when the winner
rests on little (no price, no recorded risks, no profile to fit). A thin or
close result still names a pick, because "it depends" is not advice, and says
in the same breath what would change it.

The agent writes the *words* around this (`advice.py`); it is told the result
and may not change the winner, so the pick is the same whichever agent is
connected and the same on a machine with no agent at all.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime

from app import audit, buyer, pricewatch

SEVERITY_POINTS = {"high": 10.0, "medium": 5.0, "low": 2.0}
RISK_CAP = 45.0
CLEAR_MARGIN, CLOSE_MARGIN = 12.0, 5.0


def _lean(profile: dict, name: str) -> float:
    """How much this reader cares about one thing, as a multiplier around 1."""
    weight = (profile.get("priorities") or {}).get(name)
    return 1.0 if weight is None else max(0.2, weight / 3)


def facts_of(stored: dict) -> dict:
    """The page a saved check came from, as `audit` and `buyer.fit` read a scrape."""
    request: dict = stored["request"] if isinstance(stored.get("request"), dict) else {}
    response: dict = stored["response"] if isinstance(stored.get("response"), dict) else {}
    listing: dict = response["listing"] if isinstance(response.get("listing"), dict) else {}
    fields: dict = request["fields"] if isinstance(request.get("fields"), dict) else {}
    if not fields and isinstance(listing.get("facts"), dict):
        fields = listing["facts"]
    return {
        "url": str(request.get("url") or response.get("url") or listing.get("url") or ""),
        "title": str(request.get("title") or ""),
        "description": str(request.get("description") or listing.get("description") or ""),
        "fields": fields,
    }


def entry(conn: sqlite3.Connection, stored: dict, profile: dict, *,
          now: datetime | None = None) -> dict:
    """One saved check, read into the numbers and sentences a ranking needs."""
    page = facts_of(stored)
    response: dict = stored["response"] if isinstance(stored.get("response"), dict) else {}
    name = str(stored.get("label") or page["title"] or page["url"])[:200]
    offer = pricewatch.extract(page["fields"])
    deltas: list[tuple[float, str]] = []

    verdict = None
    if offer and page["url"]:
        verdict = pricewatch.judge(conn, page["url"], offer, now=now)
        verdict["summary"] = verdict.get("summary", "")
    said = audit.listing(url=page["url"] or "https://unknown.invalid", title=page["title"] or name,
                         description=page["description"], fields=page["fields"])
    text = " ".join(str(value) for value in page["fields"].values())
    fitted = buyer.fit(profile, name=name, text=f"{page['title']} {page['description']} {text}",
                       price=offer.get("price"), currency=offer.get("currency", ""),
                       seller=said["seller"]["signals"].get("seller_name", ""))
    for reason in fitted["reasons"]:
        if reason.get("delta"):
            deltas.append((float(reason["delta"]), reason["message"]))

    claims = [one for one in response.get("claims") or [] if isinstance(one, dict)]
    risk = 0.0
    risks = {"high": 0, "medium": 0, "low": 0}
    for claim in claims:
        severity = str(claim.get("severity") or "medium")
        risks[severity] = risks.get(severity, 0) + 1
        risk += SEVERITY_POINTS.get(severity, 5.0) * (0.5 if claim.get("disputed") else 1.0)
    risk = min(RISK_CAP, risk * _lean(profile, "durability"))
    if claims:
        worst = max(claims, key=lambda one: SEVERITY_POINTS.get(str(one.get("severity")), 5.0))
        deltas.append((-risk, f"{len(claims)} known risk{'s' if len(claims) != 1 else ''}, "
                              f"worst: {worst.get('title', 'unnamed')} ({worst.get('severity', '?')})"))

    price_lean = _lean(profile, "price")
    if verdict:
        move = {"lowest": 8, "high": -8}.get(verdict["verdict"], 0) * price_lean
        if move:
            deltas.append((move, verdict["summary"]))
        discount = {"inflated": -5, "usual_price": -2, "real": 3}.get(verdict.get("discount") or "", 0)
        if discount:
            deltas.append((discount, verdict["discount_summary"]))

    level = said["seller"]["level"]
    if level == "red":
        deltas.append((-20, "; ".join(said["seller"]["notes"])))
    elif level == "amber":
        deltas.append((-6 * _lean(profile, "support"), "; ".join(said["seller"]["notes"])))
    if said["claims"]["meter"] is not None and said["claims"]["meter"] < 50 and said["claims"]["unbacked"] >= 2:
        deltas.append((-6, f"only {said['claims']['meter']}% of its checkable claims are backed on the page"))
    stars = said["reviews"].get("adjusted")
    if stars is not None:
        quality = _lean(profile, "quality")
        if stars >= 4.5:
            deltas.append((3 * quality, f"rated {stars:.1f} once few ratings are discounted"))
        elif stars < 3.5:
            deltas.append((-8 * quality, f"rated only {stars:.1f} once few ratings are discounted"))

    thin = not (offer or claims or not buyer.is_empty(profile))
    return {
        "lookup_id": str(stored.get("lookup_id") or ""), "name": name, "url": page["url"],
        "price": offer.get("price"), "currency": offer.get("currency", ""),
        "base": 50.0, "deltas": deltas, "risks": risks,
        "fit": fitted, "price_view": verdict, "audit": said, "thin": thin,
    }


def _finish(entries: list[dict], profile: dict) -> None:
    """Add the cross-candidate terms and the final score to each entry, in place."""
    lean = _lean(profile, "price")
    by_currency: dict[str, list[float]] = {}
    for one in entries:
        if one["price"] is not None:
            by_currency.setdefault(one["currency"], []).append(one["price"])
    for one in entries:
        prices = by_currency.get(one["currency"], [])
        if one["price"] is not None and len(prices) > 1:
            cheapest = min(prices)
            gap = (one["price"] - cheapest) / cheapest
            if gap > 0.05:
                more = f"{one['price'] - cheapest:g}" + (f" {one['currency']}" if one["currency"] else "")
                one["deltas"].append((-min(12.0, gap * 20) * lean, f"costs {more} more than the cheapest here"))
            elif gap <= 0.0001:
                one["deltas"].append((4.0 * lean, "the cheapest of these"))
        one["score"] = max(0.0, min(100.0, one["base"] + sum(delta for delta, _ in one["deltas"])))
        ordered = sorted(one["deltas"], key=lambda pair: pair[0])
        one["concerns"] = [text for delta, text in ordered if delta < 0][:3]
        one["strengths"] = [text for delta, text in reversed(ordered) if delta > 0][:3]


def rank(conn: sqlite3.Connection, stored: list[dict], profile: dict | None = None, *,
         now: datetime | None = None) -> dict:
    """The shortlist, best first, with a committed winner when there are two or more."""
    profile = profile if profile is not None else buyer.read(conn)
    entries = [entry(conn, one, profile, now=now) for one in stored]
    _finish(entries, profile)
    entries.sort(key=lambda one: (-one["score"], one["name"]))
    out: dict = {"ranked": [_public(one) for one in entries], "picked": None, "confidence": "",
                 "gave_up": [], "switch_if": [], "check_first": [], "profile_used": not buyer.is_empty(profile)}
    if len(entries) < 2:
        return out
    top, second = entries[0], entries[1]
    margin = top["score"] - second["score"]
    if top["thin"] and second["thin"]:
        confidence = "thin"
    elif margin >= CLEAR_MARGIN:
        confidence = "clear"
    elif margin >= CLOSE_MARGIN:
        confidence = "close"
    else:
        confidence = "toss_up"
    out["picked"] = _public(top)
    out["confidence"] = confidence
    out["margin"] = round(margin, 1)
    out["gave_up"] = top["concerns"][:2]
    if second["strengths"]:
        out["switch_if"].append(f"you weight what {second['name']} does best more heavily: "
                                + second["strengths"][0])
    if top["price"] is not None and second["price"] is not None and second["currency"] == top["currency"] \
            and second["price"] > top["price"]:
        out["switch_if"].append(f"{second['name']} falls to about {top['price']:g} {top['currency']}".strip())
    if top["concerns"]:
        out["switch_if"].append(f"you find {top['name']}'s main concern is true for your case: "
                                + top["concerns"][0])
    out["check_first"] = [text for text in top["concerns"][:2]]
    if confidence in ("thin", "toss_up"):
        out["check_first"].append("Kriko knows little to separate these: tell it your budget and "
                                  "what you must have, or research them first")
    return out


def _public(one: dict) -> dict:
    return {
        "lookup_id": one["lookup_id"], "name": one["name"], "url": one["url"],
        "price": one["price"], "currency": one["currency"], "score": round(one["score"], 1),
        "strengths": one["strengths"], "concerns": one["concerns"], "risks": one["risks"],
        "breaks": one["fit"]["breaks"], "seller": one["audit"]["seller"]["level"],
        "claims_meter": one["audit"]["claims"]["meter"],
        "price_verdict": (one["price_view"] or {}).get("verdict", ""),
        "price_view": one["price_view"],
        "thin": one["thin"],
    }


# ── committed picks, kept so they can be judged ───────────────────────────


def keep(conn: sqlite3.Connection, result: dict, *, reason: str = "") -> dict | None:
    """Remember the pick, so the ledger can later say whether it was right."""
    picked = result.get("picked")
    if not picked:
        return None
    pick_id = secrets.token_hex(8)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO picks (pick_id, created_at, winner_name, winner_url, reason, pick_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (pick_id, now, picked["name"][:300], picked["url"][:2000], reason[:2000],
         json.dumps({"ranked": result["ranked"], "confidence": result["confidence"],
                     "gave_up": result["gave_up"], "switch_if": result["switch_if"]},
                    ensure_ascii=False)))
    conn.execute("DELETE FROM picks WHERE pick_id NOT IN"
                 " (SELECT pick_id FROM picks ORDER BY created_at DESC LIMIT 200)")
    conn.commit()
    return {"pick_id": pick_id, "created_at": now, "winner": picked["name"]}


def track_record(conn: sqlite3.Connection) -> dict:
    """How Kriko's own picks turned out, from the ledger: bought what it picked, and how it went.

    A pick counts as followed when the reader later recorded a purchase of the
    same product (by page, else by name). Only answered purchases score. A
    track record with fewer than three answered picks says so instead of a rate.
    """
    picks = conn.execute("SELECT winner_name, winner_url FROM picks").fetchall()
    followed = glad = regret = 0
    for pick in picks:
        row = conn.execute(
            "SELECT verdict FROM purchases WHERE verdict != '' AND (url != '' AND url = ? OR name = ?)"
            " ORDER BY bought_at DESC LIMIT 1", (pick["winner_url"], pick["winner_name"])).fetchone()
        if row:
            followed += 1
            glad += row["verdict"] in ("glad", "fine")
            regret += row["verdict"] == "regret"
    return {"picks": len(picks), "followed_and_answered": followed, "held_up": glad,
            "regretted": regret,
            "rate": round(glad / followed, 2) if followed >= 3 else None,
            "note": "" if followed >= 3 else "too few answered picks to say how often they held up"}
