"""A listing audited against itself: the seller, the score, and the big words.

A listing makes three kinds of statement a buyer cannot check from the listing
alone, and each can be tested against the same page without a model:

* **Who sells it.** The site's tier (`exactfind.classify`: a marketplace is only
  as good as its seller) and what the page says about the seller in its own
  words (`exactfind.seller_signals`).
* **How well it is rated.** A 4.9 from eleven buyers and a 4.6 from nine
  thousand are different facts. `reviews` shrinks a score toward an ordinary
  one by how few people gave it, and names the shapes that deserve doubt: a
  perfect score, a score with no count, a high score on a handful of voices.
* **What it claims.** "Waterproof", "original", "lifetime warranty", "best".
  Each is a kind of claim with a kind of evidence it would need: a rating, an
  authorised-seller line, a figure. `claims` reads the title and description
  for claim words, then looks in the page's own labelled facts for that
  evidence. A claim with none is not called false; it is called **unbacked**,
  because the page not showing a figure is not the product lacking one.

The claim words are data (`CLAIM_KINDS`), in the languages the readers' sites
write in, and say nothing about any product category: they are the words
sellers use to be believed.

Pure functions of the scrape. Everything returned is a statement the reader can
check on the page, and the meter says how much of what the page *claims* it
also *shows*, never how good the product is.
"""

from __future__ import annotations

import re
import unicodedata

from app import exactfind

#: How many ordinary reviews a score is shrunk toward. A score from far fewer
#: people than this is mostly the prior.
PRIOR_COUNT = 12
PRIOR_MEAN = 3.9


def _fold(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).casefold().replace("ı", "i")
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).split())


def _float(value) -> float | None:
    try:
        number = float(str(value).replace(",", ".").split("/")[0].strip())
    except ValueError:
        return None
    return number


# ── reviews ──────────────────────────────────────────────────────────────


def reviews(fields: dict | None) -> dict:
    """The page's rating, weighed by how many gave it. `{}` when it shows none."""
    fields = fields if isinstance(fields, dict) else {}
    rating = _float(fields.get("ld:ratingValue"))
    if rating is None:
        return {}
    best = _float(fields.get("ld:bestRating"))
    best = 5.0 if best is None else best
    if best <= 0:
        return {}
    stars = rating / best * 5
    if not 0 < stars <= 5.0001:
        return {}
    raw_count = _float(re.sub(r"[^\d.,]", "", str(fields.get("ld:reviewCount") or "")) or "x")
    count = int(raw_count) if raw_count is not None and raw_count >= 0 else None
    notes: list[str] = []
    adjusted = stars
    if count is None:
        notes.append("the page shows a score but not how many people gave it")
    else:
        adjusted = (stars * count + PRIOR_MEAN * PRIOR_COUNT) / (count + PRIOR_COUNT)
        if count < 10 and stars >= 4.5:
            notes.append(f"{stars:.1f} from only {count} rating{'s' if count != 1 else ''} is "
                         "mostly noise")
        if stars >= 4.95 and count >= 30:
            notes.append(f"a flawless {stars:.1f} from {count} people is rare in real reviews")
        if count == 0:
            notes.append("a score with zero ratings behind it")
    return {
        "stars": round(stars, 2), "count": count, "adjusted": round(adjusted, 2),
        "doubtful": bool(notes), "notes": notes,
    }


# ── the seller ───────────────────────────────────────────────────────────


def seller(url: str, fields: dict | None, text: str = "") -> dict:
    """Who sells it: the site's tier, plus what the page says about the seller itself."""
    fields = fields if isinstance(fields, dict) else {}
    site = exactfind.classify(url)
    said = " ".join(str(value) for key, value in fields.items()
                    if not str(key).startswith("ld:") or key in ("ld:seller",))[:6000]
    signals = exactfind.seller_signals(f"{text}\n{said}")
    named = str(fields.get("ld:seller") or "").strip()
    if named and "seller_name" not in signals:
        signals["seller_name"] = named
    notes: list[str] = []
    risk = 0
    if site["tier"] == "marketplace" and not (signals.get("seller_name") or signals.get("official_claim")):
        notes.append("a marketplace listing that does not name its seller")
        risk += 1
    if site["tier"] in ("classified", "unknown"):
        notes.append(f"{site['label']}: nobody vouches for this seller")
        risk += 1
    if signals.get("red_flags"):
        notes.append("asks for payment by " + ", ".join(signals["red_flags"]))
        risk += 3
    if signals.get("official_claim") and site["tier"] in ("marketplace", "classified", "unknown"):
        notes.append("calls itself official on a site where anyone can say that")
        risk += 1
    return {"site": site, "signals": signals, "notes": notes,
            "level": "red" if risk >= 3 else "amber" if risk else "green"}


# ── the big words ────────────────────────────────────────────────────────

#: A kind of claim, the words that make it, and the evidence that would back it.
#: `needs` is looked for in the page's own labelled facts and description;
#: `needs: None` marks a claim no figure could back (puffery). Add a language
#: or a kind here, never in code.
CLAIM_KINDS: dict[str, dict] = {
    "authentic": {
        "words": r"original|orijinal|genuine|authentic|100% original|sifir|orjinal|echt|authentique",
        "needs": "seller",
        "why_unbacked": "'original' is the seller's word; nothing on the page shows the maker "
                        "or an authorised dealer stands behind it",
    },
    "water": {
        "words": r"waterproof|water[- ]resistant|su gecirmez|suya dayanikli|splash[- ]proof|wasserdicht",
        "needs": r"\bip\s?[0-9x]{2}\b|\b\d+\s?atm\b|\b\d+\s?(?:m|metre|meter|bar)\b|water resistance|su direnci",
        "why_unbacked": "no water-resistance rating (an IP code, ATM or depth) on the page",
    },
    "warranty": {
        "words": r"warranty|guarantee|garanti|garantie|lifetime",
        "needs": r"\b\d+\s?(?:year|yr|month|ay|yil|jahr|monat|mois|an)s?\b|\b\d+\s?(?:-|\s)year\b",
        "why_unbacked": "no length of warranty, or who gives it, on the page",
    },
    "performance": {
        "words": r"fast charg\w*|hizli sarj|ultra[- ]fast|long[- ]lasting battery|all[- ]day battery|"
                 r"high[- ]performance|powerful|yuksek performans|guclu",
        "needs": r"\b\d+(?:[.,]\d+)?\s?(?:w|kw|mah|wh|hrs?|hours?|saat|gb|tb|mbps|gbps|hz|rpm|nm|lm|"
                 r"mp|megapixel|fps|ms)\b",
        "why_unbacked": "a performance word with no figure beside it",
    },
    "certified": {
        "words": r"certified|approved|tested|clinically|dermatologically|sertifikali|onayli|zertifiziert|"
                 r"tuv|test edilmis",
        "needs": r"\b(?:ce|ul|iso\s?\d+|tuv|fcc|rohs|gs|ecocert|fsc|energy star|\d+/\d+/ec)\b",
        "why_unbacked": "'certified' or 'tested' with no certificate or standard named",
    },
    "natural": {
        "words": r"100%|pure|natural|organic|dogal|saf\b|organik|bio\b|chemical[- ]free",
        "needs": r"ingredient|composition|icindekiler|material|malzeme|content|fabric|kumas|zutaten",
        "why_unbacked": "a purity claim with no ingredients or materials listed",
    },
    "best": {
        "words": r"\bbest\b|#1|number one|top[- ]rated|world'?s? (?:best|first|leading)|en iyi|no\.? ?1|"
                 r"unbeatable|ultimate|perfect|mukemmel|beste\b|le meilleur",
        "needs": None,
        "why_unbacked": "a superlative: no measurement can back it",
    },
    "tough": {
        "words": r"unbreakable|indestructible|military[- ]grade|bulletproof|scratch[- ]proof|"
                 r"kirilmaz|darbeye dayanikli|askeri",
        "needs": r"mil-?std|gorilla|sapphire|\bmohs\b|drop test|test report|"
                 r"\b\d+(?:[.,]\d+)?\s?(?:m|ft|cm)\s?drop",
        "why_unbacked": "a toughness claim with no test or standard named",
    },
    "urgency": {
        "words": r"limited time|only today|last \d+|hurry|son \d+ adet|sadece bugun|firsat|"
                 r"almost gone|selling fast|\d+ people (?:are )?viewing",
        "needs": None,
        "why_unbacked": "urgency wording; it says nothing about the product",
    },
}


def claims(title: str, description: str, fields: dict | None, seller_info: dict | None = None) -> dict:
    """The big words a listing uses, and whether the page shows what they would need.

    `status` per claim is `backed` (the evidence appears on the page),
    `unbacked` (it does not), `seller_word` (the claim is only as good as the
    seller, and the seller is not shown to be authorised) or `puffery` (no
    evidence could exist). `meter` is the share of *checkable* claims that are
    backed, `None` when the page makes none.
    """
    fields = fields if isinstance(fields, dict) else {}
    claimed = _fold(f"{title} {description}")
    shown = _fold(" ".join(f"{key} {value}" for key, value in fields.items()
                           if str(key) != "ld:@type") + f" {description}")
    out: list[dict] = []
    for kind, spec in CLAIM_KINDS.items():
        hit = re.search(rf"(?<![a-z0-9])(?:{spec['words']})", claimed)
        if not hit:
            continue
        needs = spec["needs"]
        if needs is None:
            status = "puffery"
        elif needs == "seller":
            # An official-dealer line counts only where a seller cannot simply write it.
            site = (seller_info or {}).get("site", {})
            status = "backed" if (seller_info or {}).get("signals", {}).get("official_claim") and \
                site.get("tier") not in ("marketplace", "classified", "unknown") else "seller_word"
        else:
            status = "backed" if re.search(needs, shown) else "unbacked"
        out.append({"kind": kind, "phrase": hit.group(0).strip(), "status": status,
                    "why": "" if status == "backed" else spec["why_unbacked"]})
    checkable = [one for one in out if one["status"] != "puffery"]
    backed = sum(1 for one in checkable if one["status"] == "backed")
    return {
        "items": out,
        "meter": round(100 * backed / len(checkable)) if checkable else None,
        "unbacked": sum(1 for one in out if one["status"] in ("unbacked", "seller_word")),
    }


def listing(*, url: str, title: str = "", description: str = "", fields: dict | None = None) -> dict:
    """The whole audit of one scrape: seller, rating, claims, and one line to lead with."""
    fields = fields if isinstance(fields, dict) else {}
    who = seller(url, fields, f"{title}\n{description}")
    rated = reviews(fields)
    said = claims(title, description, fields, who)
    lines: list[str] = []
    if who["level"] == "red":
        lines.append("Seller: " + "; ".join(who["notes"]))
    if rated.get("doubtful"):
        lines.append("Rating: " + "; ".join(rated["notes"]))
    if said["unbacked"]:
        lines.append(f"{said['unbacked']} claim{'s' if said['unbacked'] != 1 else ''} the page "
                     "does not back up")
    return {"seller": who, "reviews": rated, "claims": said, "headline": lines[0] if lines else "",
            "flags": lines}
