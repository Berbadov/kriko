"""Finding the exact product, and judging who sells it.

A buying question has three ways to go wrong, and a fluent answer hides all of
them: the product is close but not the one (the right oil, the wrong approval;
the right filter, the wrong engine), the page is not a place to buy (a content
farm, a classified ad), or the seller is a stranger on a good site. This module
gives the answer something to check each against, from the pages themselves:

* **Who** — `classify` places a site in a tier from `sellers.json`. The file is
  data, so a site is added without a code change. A marketplace is a tier of its
  own because its trust belongs to the seller on the page, not to the site.
* **Which first** — `rank` puts trusted, different sites ahead of the search
  engine's order, so the pages that are read are the ones worth reading.
* **Which one** — `identifiers` finds the codes a page prints (part numbers,
  model numbers, viscosity grades) and counts how many independent sites print
  the same one. A code on one site is a claim; on two, with one trusted, it is
  a match.
* **Who says so** — `seller_signals` copies what a page says about its seller:
  an official or authorised claim, the seller's name, a score, a company
  identity, a payment method that scams use. They are the page's own words about
  itself. The answer must say "the page says", never "this seller is".

Pure functions of text. No model call, no network, and no product category: the
registry names kinds of shops, and a code is any mixed run of letters and digits.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

#: Pages a buying turn gathers before it reads the best of them.
BUY_RESULTS_CAP = 8
#: Codes the answer is shown, most corroborated first.
IDENTIFIERS_CAP = 12
#: Trusted sites a first search must already hold before a second, targeted
#: search is skipped. Below it the engine's own ranking found too few places to
#: buy from, and one more query is cheaper than a thin answer.
ENOUGH_TRUSTED = 2
#: A tier at or above this trust counts as a place a reader may buy from.
TRUSTED_AT = 0.6
#: Trust a page loses for each earlier page of the same site in the ranking.
REPEAT_PENALTY = 0.2


def fold(text: object) -> str:
    """Lower-case text without accents, with the Turkish dotless i as `i`."""
    folded = unicodedata.normalize("NFKD", str(text or "").casefold().replace("ı", "i"))
    return "".join(c for c in folded if not unicodedata.combining(c))


# ── who ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def registry() -> dict:
    """The shipped `sellers.json` with the reader's own over it, read once per run.

    The reader's file is `~/.kriko/sellers.json`, in the same shape. It is the
    place to add or demote a site, because the shipped file sits inside the
    installed app. Restart Kriko after an edit.
    """
    try:
        from app.web.settings import KRIKO_HOME
        return load_registry(KRIKO_HOME)
    except Exception:  # noqa: BLE001 - no home directory is the shipped registry
        return load_registry(None)


def load_registry(home) -> dict:
    """`sellers.json` as the shipped file says it, with `home`'s file merged over it.

    Each site's tier is looked up by registrable domain. The reader's sites are
    read first and a first claim on a domain wins, so a reader can move a site
    to another tier. An unreadable or malformed reader's file is ignored: a typo
    there must never stop a search.
    """
    shipped = json.loads(files("app").joinpath("sellers.json").read_text(encoding="utf-8"))
    mine: dict = {}
    if home is not None:
        try:
            mine = json.loads((Path(home) / "sellers.json").read_text(encoding="utf-8"))
            if not isinstance(mine, dict):
                mine = {}
        except (OSError, ValueError):
            mine = {}
    tiers = {**shipped["tiers"]}
    for name, spec in (mine.get("tiers") or {}).items():
        if isinstance(spec, dict) and "trust" in spec and "label" in spec:
            tiers[name] = spec
    by_domain: dict[str, str] = {}
    for entry in [*(mine.get("sites") or []), *shipped.get("sites", [])]:
        try:
            tier = entry["tier"]
            if tier not in tiers:
                continue
            for domain in entry.get("domains", []):
                by_domain.setdefault(str(domain).lower(), tier)
            label = entry.get("label")
            if label:
                for tld in entry.get("tlds", []):
                    by_domain.setdefault(f"{label}.{tld}".lower(), tier)
        except (KeyError, TypeError, AttributeError):
            continue
    suffixes = {**shipped.get("suffixes", {}), **(mine.get("suffixes") or {})}
    return {
        "tiers": tiers,
        "by_domain": by_domain,
        "suffixes": [(s.lower(), tier) for tier, ones in suffixes.items() if tier in tiers
                     for s in ones],
        "regions": {**shipped.get("regions", {}), **(mine.get("regions") or {})},
    }


def registrable(url: str) -> str:
    """Registrable domain, shared with the local pipeline without loading it."""
    from app.domains import publisher

    return publisher(url)


def _question_words(question: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", fold(question)) if len(w) >= 4}


def classify(url: str, question: str = "") -> dict:
    """The tier of a site: `{domain, tier, label, trust, note?}`.

    A listed site wins. Then a domain named exactly after a brand the reader
    wrote (`<brand>.<tld>`) is a `brand_site`, because the maker's own shop is
    the best place to confirm a code and cannot be listed by name in advance.
    Public bodies follow by suffix. Anything else is `unknown`, and unknown is
    a finding: the answer is told not to call its seller reliable.
    """
    reg = registry()
    domain = registrable(url)
    host = (urlsplit(url if "//" in url else f"//{url}").hostname or "").lower()
    tier = reg["by_domain"].get(domain)
    if tier is None and domain.split(".")[0] in _question_words(question):
        tier = "brand_site"
    if tier is None:
        tier = next((t for suffix, t in reg["suffixes"] if host.endswith(suffix)), "unknown")
    spec = reg["tiers"][tier]
    out = {"domain": domain, "tier": tier, "label": spec["label"], "trust": spec["trust"]}
    if spec.get("note"):
        out["note"] = spec["note"]
    return out


def is_trusted(trust: dict | None) -> bool:
    return trust is not None and float(trust.get("trust", 0)) >= TRUSTED_AT


def rank(rows: list[dict]) -> list[dict]:
    """Rows reordered: most trusted first, and different sites before repeats.

    Stable, so rows of equal trust keep the search engine's order. Three pages of
    one shop agree with each other for the wrong reason, so each repeat of a site
    ranks lower (`REPEAT_PENALTY`) than the first page of another site of the
    same trust, but not lower than a site nobody trusts.
    """
    by_trust = sorted(enumerate(rows), key=lambda item: (
        -float((item[1].get("source_trust") or {}).get("trust", 0)), item[0]))
    seen: dict[str, int] = {}
    scored: list[tuple[float, int, dict]] = []
    for index, row in by_trust:
        trust = row.get("source_trust") or {}
        domain = trust.get("domain") or registrable(row.get("url", ""))
        # Each earlier page of a site costs the next one a little trust: a second
        # page of a good shop still beats an unknown site, and a third does not
        # beat a different good shop.
        scored.append((float(trust.get("trust", 0)) - REPEAT_PENALTY * seen.get(domain, 0),
                       index, row))
        seen[domain] = seen.get(domain, 0) + 1
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored]


def trusted_count(rows: list[dict]) -> int:
    """How many different trusted sites the rows come from."""
    return len({(row.get("source_trust") or {}).get("domain")
                for row in rows if is_trusted(row.get("source_trust"))})


def region_of(question: str) -> str:
    """The shopping region the question's own language points at, else `global`."""
    text = str(question or "")
    # A Turkish-only letter settles it. Plain-ASCII Turkish ("yag ve filtre")
    # is common in a chat box, so two Turkish function words settle it too.
    if re.search(r"[ğĞşŞıİ]", text) or _turkish_words(text) >= 2:
        return "tr"
    return "global"


#: Function words of one language, to tell it apart. Not a product vocabulary.
_TURKISH_WORDS = frozenset(
    "icin ve bir gerekli nereden nerede fiyat lazim bulabilir bulur alabilir alabilirim "
    "misin musun yag filtre motorlu stokta ucuz siparis satin uygun hangi bana bunlari "
    "bunu icin ile mi mu".split())


def _turkish_words(text: str) -> int:
    return sum(w in _TURKISH_WORDS for w in re.findall(r"[a-z]+", fold(text)))


def targeted_query(query: str, region: str = "global", sites: int = 4) -> str:
    """The query again, limited to the sites a reader in that region buys from."""
    domains = registry()["regions"].get(region) or registry()["regions"].get("global", [])
    scope = " OR ".join(f"site:{d}" for d in domains[:sites])
    return f"{query[:240]} ({scope})" if scope else query


#: The words a mode adds to the search, per region. Function words of one
#: language, not a product vocabulary: a new category needs no entry here.
_MODE_WORDS = {
    "alternatives": {"global": "alternatives", "tr": "alternatif muadil"},
    "cheapest": {"global": "price", "tr": "fiyat"},
    "merchants": {"global": "seller reviews", "tr": "satici yorumlari"},
}


def mode_query(query: str, mode: str, region: str = "global") -> str:
    """The query again, shaped for a Chat mode, or empty when the mode adds nothing.

    A second search beside the first, never instead of it: the first finds the
    product, this one finds what the mode is about (other products, prices,
    the people selling it). Pages are ranked and read as for any buying turn.
    """
    words = _MODE_WORDS.get(mode)
    if not words:
        return ""
    extra = words.get(region) or words["global"]
    return f"{query[:240]} {extra}"


# ── did the reader ask to buy ────────────────────────────────────────────

_BUY = re.compile(
    r"\b(?:buy|buying|purchase|order|shop|shopping|price|prices|cost|cheap|cheaper|cheapest|"
    r"deal|in stock|for sale|where (?:can|could|do|should|would) (?:i|we) (?:get|find|order|buy|"
    r"source|purchase)|(?:can|could|would|will) you (?:please )?(?:find|look for|locate|source|"
    r"get|order)|looking for|i (?:need|want)|replacement|compatible|fits?|"
    r"seller|retailer|supplier|dealer|"
    r"bulabilir\s*mi\w*|bulur\s*mu\w*|nereden|nerede|fiyat\w*|ucuz\w*|stok\w*|siparis\w*|"
    r"satin\w*|alabilir\w*|lazim|gerekli|ihtiyac\w*|uygun|satici\w*|magaza\w*|"
    r"kaufen|bestellen|preis\w*|acheter|commander|prix|comprar|precio\w*|donde)\b", re.I)


def is_purchase_request(message: str) -> bool:
    """Whether the reader wants something to buy, not only a fact.

    Wide on purpose, in the words people use rather than "buy": the cost of a
    false yes is a longer brief and one more search; the cost of a false no is
    an answer with no seller check.
    """
    return bool(_BUY.search(fold(message)))


# ── which one ────────────────────────────────────────────────────────────

_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9.\-]{2,22}[A-Za-z0-9](?![A-Za-z0-9])")
#: Figures with a unit are measurements, not part numbers: `1.5dci`, `5l`, `16v`.
_MEASURE = re.compile(
    r"^\d+(?:[.,]\d+)?(?:mm|cm|m|km|kg|g|mg|gb|tb|mb|kb|hz|khz|mhz|ghz|w|kw|v|a|ah|mah|l|lt|ml|"
    r"cl|cc|hp|ps|bhp|nm|rpm|dci|tdi|tdci|hdi|cdi|crdi|tsi|tfsi|inch|in|pcs|pc|adet)$|"
    r"^\d+x\d+(?:x\d+)?$", re.I)
_ADDRESS = re.compile(r"\.[A-Za-z]{2,6}$|^www\.|^[A-Za-z]+\.[A-Za-z]+\.", re.I)
_YEARISH = re.compile(r"^(?:19|20)\d{2}[a-z]?$", re.I)
#: The two short shapes worth keeping below five characters: a viscosity grade
#: (`5W-30`) and an approval code (`RN17`). Both only count when two sites print them.
_VISCOSITY = re.compile(r"^(?:\d{1,2}W\d{2}|[A-Z]{2}\d{2})$")


def normalise_code(token: str) -> str:
    """`152 092-567r` and `152092567R` are one code."""
    return re.sub(r"[^A-Z0-9]", "", token.upper())


#: Part numbers are often printed in groups: `152 092 567 R`, `0 986 AF2 107`.
#: Every group holds a digit, and the whole is long enough that two figures and
#: a unit (`6 5W 30`) cannot pass for one.
_GROUP = r"[A-Za-z]{0,2}\d[A-Za-z\d]{0,3}"
_SPACED = re.compile(rf"(?<![A-Za-z0-9.]){_GROUP}(?: {_GROUP}){{2,4}}(?![A-Za-z0-9])")
_SPACED_MIN = 8


def _codes_in(text: str) -> dict[str, str]:
    """Each code-like token of a text, as `{normalised: as written}`."""
    found: dict[str, str] = {}
    text = text or ""
    candidates = [(m.group(0).strip(".-"), 5) for m in _TOKEN.finditer(text)]
    # (the shortest a code may be, per source of the candidate)
    # A run of measurements (`5L 16V`) is not a code printed in groups.
    candidates += [(m.group(0), _SPACED_MIN) for m in _SPACED.finditer(text)
                   if not any(_MEASURE.match(group) for group in m.group(0).split())]
    for token, shortest in candidates:
        norm = normalise_code(token)
        # A viscosity grade (`5W-30`) is the one four-character code worth keeping.
        if not (shortest <= len(norm) <= 20 or _VISCOSITY.match(norm)):
            continue
        if not (re.search(r"\d", norm) and re.search(r"[A-Z]", norm)):
            continue
        if _MEASURE.match(token) or _ADDRESS.search(token) or _YEARISH.match(norm):
            continue
        # A long run of hex digits is a hash or a tracking id, not a part.
        if len(norm) >= 16 and re.fullmatch(r"[0-9A-F]+", norm):
            continue
        found.setdefault(norm, token)
    return found


def identifiers(rows: list[dict], question: str = "") -> list[dict]:
    """The codes the fetched pages print, with how many sites print each.

    `[{"code", "sites", "trusted_sites", "confirmed", "in_question", "on": [...]}]`,
    most corroborated first. `confirmed` is two different trusted sites: the bar
    the answer is told to hold before it says "exact". An unrecognised site that
    repeats a code adds to `sites` and never to `confirmed`, because a scraper
    that copied a catalogue agrees with it for the wrong reason. A code the
    reader wrote themselves is `in_question`, and a page that prints it is
    evidence for that code, not a new one.
    """
    wanted = set(_codes_in(question))
    seen: dict[str, dict] = {}
    for row in rows:
        if not row.get("page_read"):
            continue
        trust = row.get("source_trust") or {}
        domain = trust.get("domain") or registrable(row.get("url", ""))
        text = f"{row.get('title', '')} {row.get('page_excerpt', '')}"
        for norm, shown in _codes_in(text).items():
            entry = seen.setdefault(norm, {"code": shown, "domains": set(), "trusted": set()})
            entry["domains"].add(domain)
            if is_trusted(trust):
                entry["trusted"].add(domain)
    out = [{
        "code": e["code"], "sites": len(e["domains"]), "trusted_sites": len(e["trusted"]),
        "confirmed": len(e["trusted"]) >= 2,
        "in_question": norm in wanted, "on": sorted(e["domains"])[:4],
    } for norm, e in seen.items()]
    out.sort(key=lambda e: (-e["sites"], -e["trusted_sites"], not e["in_question"], e["code"]))
    # One site's catalogue prints hundreds of codes. A code only that site prints
    # tells the reader nothing about this product, so singles are kept only when
    # the reader named them or too few codes are corroborated to leave a list.
    multi = [e for e in out if e["sites"] >= 2 or e["in_question"]]
    return (multi or out)[:IDENTIFIERS_CAP]


def codes_on(row: dict, confirmed: set[str], limit: int = 5) -> list[str]:
    """The codes of one page that other pages also print, for its row."""
    norms = _codes_in(f"{row.get('title', '')} {row.get('page_excerpt', '')}")
    return [shown for norm, shown in norms.items() if norm in confirmed][:limit]


# ── who says so ──────────────────────────────────────────────────────────

_OFFICIAL = re.compile(
    r"\b(?:official (?:store|shop|dealer|partner|retailer)|authori[sz]ed (?:dealer|reseller|"
    r"retailer|seller|distributor|partner|service)|resmi (?:magaza|satici|bayi|distribut\w+)|"
    r"yetkili (?:satici|bayi|servis|distribut\w+|toptanci)|offizielle[rn]? (?:shop|h(?:ae?)ndler)|"
    r"autorisierte[rn]? h(?:ae?)ndler|boutique officielle|revendeur agree|distributeur agree)\b")
# The keyword is case-blind; the name that follows must start with a capital or
# a digit, so "seller is not responsible for…" is not read as a seller called "is".
_SOLD_BY = re.compile(
    r"(?i:sold (?:and shipped )?by|ships from and sold by|seller|vendu par|verkauf(?:t)? "
    r"(?:durch|von)|sat[ıi]c[ıi]|ma[gğ]aza)\s*[:\-–]?\s*"
    # "Seller Rating: 9.4" names no seller, and neither do the headings below.
    r"(?!(?i:rating|score|feedback|information|info|policy|profile|reviews?|puan\w*|"
    r"degerlendirme\w*|bilgi\w*|hakk\w*)\b)"
    r"([A-Z0-9][\w&.'’-]*(?: [\w&.'’-]+){0,4})")
#: Words that start the next label, so a seller's name stops before them.
_NAME_ENDS = frozenset("satici seller magaza puan puani rating vergi vkn tax vat sold ships by "
                       "from shipped fulfilled".split())
_RATING = re.compile(
    r"(?i:seller (?:rating|score|feedback)|sat[ıi]c[ıi] puan[ıi]|ma[gğ]aza puan[ıi])"
    r"\D{0,15}(\d{1,2}(?:[.,]\d{1,2})?(?:\s*/\s*\d{1,3}|\s*%)?)")
_COMPANY = re.compile(
    r"\b(?:vergi (?:no|numaras\w*)|vkn|mersis|ticaret sicil\w*|vat (?:id|no|number)|tax id|"
    r"company (?:no|number|registration)|impressum|handelsregister|siret|ust-?id|kep adresi)\b")
_RED_FLAG = re.compile(
    r"\b(?:western union|moneygram|bitcoin|crypto(?:currency)?|gift cards?|hediye karti|zelle|"
    r"cash app|sadece havale|yalnizca havale|only (?:accept(?:s|ed)? )?(?:bank|wire) transfer)\b")


def seller_signals(text: str) -> dict:
    """What a page says about its seller, in its own words. Empty when it says nothing.

    These are claims by the page about itself. The answer repeats them as "the
    page says" and never as a finding of Kriko's.
    """
    raw = str(text or "")
    folded = fold(raw)
    out: dict = {}
    official = _OFFICIAL.search(folded)
    if official:
        out["official_claim"] = official.group(0)
    sold = _SOLD_BY.search(raw)
    if sold:
        name: list[str] = []
        for word in sold.group(1).split()[:5]:
            if fold(word).strip(".,;:") in _NAME_ENDS:
                break
            name.append(word)
        if name:
            out["seller_name"] = " ".join(name).strip(".,;:-")
    rating = _RATING.search(raw)
    if rating:
        out["seller_rating"] = " ".join(rating.group(1).split())
    if _COMPANY.search(folded):
        out["company_identity_shown"] = True
    flags = sorted({m.group(0) for m in _RED_FLAG.finditer(folded)})
    if flags:
        out["red_flags"] = flags[:4]
    return out
