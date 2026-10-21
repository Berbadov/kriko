"""How thin a finding's evidence is, derived from the finding itself.

The reader's words: "info sensitivity setting, showing or not showing thin
evidences, with an indicator next to info cards." This module is the one place
that decides what *thin* means, so the desktop app and the browser extension
draw the same indicator and hide the same cards.

**Never a list of products.** Every rule reads the claim row it is given and
nothing else: how many different sites say it, how far the best of them is
trusted, whether the quote it carries is whole, whether a condition on it
could not be checked against this product. The engine ranks, the interface
filters: nothing here is stored, and no setting changes a claim or a
`content_digest`.

The contract other code reads (field names are stable)
-----------------------------------------------------

The setting `info_sensitivity` (`prefs.INFO_SENSITIVITY`) is stored by
`PUT /api/prefs` and read from `GET /api/settings`, which always carries it
(`"all"` when the reader never chose). Its values:

    all         draw every finding (the default; nothing is hidden)
    hide_thin   hide findings whose level is `thin`
    strict      draw only findings whose level is `solid`

A claim row served by `/api/lookup` and `/api/analyze` carries an `evidence`
object, added by `annotate`:

    "evidence": {
        "level":   "solid" | "partial" | "thin",
        "reasons": [{"code": <code>, "text": <sentence for hover or focus>}]
    }

`code` is one of `single_source`, `low_trust`, `partial_quote`,
`unmet_condition`, `no_source`. `solid` has no reasons; `partial` has one;
`thin` has two or more. Each `sources[]` item also carries `trust`, the
number the engine ranked it by. `shown(level, sensitivity)` is the whole
filter, and `hidden_count` words the "3 thin findings hidden" line.

What a claim row may carry, all optional
----------------------------------------

`sources[]`: `url`, `domain`, `quote`, `stance`, `tier`, `trust`, `standing`
(`trusted`, `neutral` or `low`, added by `annotate` from `trust`), and
`quote_match` (`"exact"`, `"partial"`, `"missing"`, or a ratio from 0 to 1,
as `factcheck` or a pipeline can say it). `open_conditions`: the reasons of
conditions that the listing did not state, which the engine served anyway. A
field that is absent is no doubt: the function fails open and names only what
the row says.
"""

from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from kriko.lookup.rank import DEFAULT_TIER_TRUST

SOLID, PARTIAL, THIN = "solid", "partial", "thin"
LEVELS = (SOLID, PARTIAL, THIN)

ALL, HIDE_THIN, STRICT = "all", "hide_thin", "strict"
SENSITIVITIES = (ALL, HIDE_THIN, STRICT)
DEFAULT_SENSITIVITY = ALL

#: Less trusted than a site nobody has classified. The engine's own neutral
#: tier is the yardstick, so a pack that re-weights its tiers moves this too
#: and nothing here names a tier.
LOW_TRUST_BELOW = DEFAULT_TIER_TRUST["unknown"]

#: The words a source's quote match may use, mapped to how whole they are.
_WHOLE = {"exact", "verbatim", "full", "quoted", "whole"}
_PART = {"partial", "loose", "fuzzy", "approximate", "partly"}
_NONE = {"missing", "none", "absent", "not_found", "unmatched"}

_TEXT = {
    "single_source": "Only one site says this. Nothing else confirms it yet.",
    "low_trust": "The best source for this is a low-trust kind of site, such as a forum or an ad-driven blog.",
    "partial_quote": "The quote behind this is missing, or only partly matches its page.",
    "unmet_condition": "This depends on a detail your listing does not state, so it may not apply to your product.",
    "no_source": "This cites no page. It may be a scheduled item rather than a reported fault.",
}


def normalise(value: object) -> str:
    """A stored setting as one of `SENSITIVITIES`; anything else is `all`."""
    word = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return word if word in SENSITIVITIES else DEFAULT_SENSITIVITY


def shown(level: str, sensitivity: object) -> bool:
    """Whether the reader's setting draws a finding of this level."""
    chosen = normalise(sensitivity)
    if chosen == STRICT:
        return level == SOLID
    if chosen == HIDE_THIN:
        return level != THIN
    return True


def hidden_count(levels: Iterable[str], sensitivity: object) -> int:
    """How many of these findings the setting leaves out."""
    return sum(1 for level in levels if not shown(level, sensitivity))


def _host(source: Mapping) -> str:
    domain = str(source.get("domain") or "").strip().lower()
    if domain:
        return domain.removeprefix("www.")
    url = str(source.get("url") or "")
    host = (urlsplit(url if "//" in url else f"//{url}").hostname or "").lower()
    return host.removeprefix("www.")


def _trust(source: Mapping) -> float | None:
    """How far a source is trusted: the engine's number, else its tier's, else
    what `exactfind` makes of the address. `None` when nothing says."""
    number = source.get("trust")
    if isinstance(number, (int, float)) and not isinstance(number, bool):
        return float(number)
    tier = str(source.get("tier") or "")
    if tier in DEFAULT_TIER_TRUST:
        return DEFAULT_TIER_TRUST[tier]
    if tier or source.get("url"):
        from app import exactfind

        try:
            if tier and tier in exactfind.registry()["tiers"]:
                return float(exactfind.registry()["tiers"][tier]["trust"])
            if source.get("url"):
                return float(exactfind.classify(str(source["url"]))["trust"])
        except Exception:  # noqa: BLE001 - a registry that cannot be read is no doubt
            return None
    return None


def _whole(source: Mapping) -> bool | None:
    """Whether this source's quote is whole: `None` when nothing says."""
    match = source.get("quote_match")
    if isinstance(match, bool):
        return match
    if isinstance(match, (int, float)):
        return float(match) >= 1.0
    word = str(match or "").strip().lower()
    if word in _WHOLE:
        return True
    if word in _PART or word in _NONE:
        return False
    if source.get("quote_grounded") is False:
        return False
    # No verdict was recorded. A citation with no quote at all cannot be whole.
    return None if str(source.get("quote") or "").strip() else False


def reasons(claim: Mapping) -> list[dict]:
    """Why this claim is thin, as `{"code", "text"}` rows, in a fixed order."""
    sources = [s for s in (claim.get("sources") or []) if isinstance(s, Mapping)]
    supporting = [s for s in sources if str(s.get("stance") or "supports") != "refutes"]
    found: list[str] = []
    if not supporting:
        # A scheduled-maintenance claim is due unless something proves
        # otherwise and cites nothing; that is partial doubt, never thin.
        found.append("no_source")
    else:
        distinct = {_host(s) or str(s.get("url") or f"#{at}") for at, s in enumerate(supporting)}
        if len(distinct) == 1:
            found.append("single_source")
        trusts = [t for t in (_trust(s) for s in supporting) if t is not None]
        if trusts and max(trusts) < LOW_TRUST_BELOW:
            found.append("low_trust")
        wholes = [_whole(s) for s in supporting]
        if all(w is False for w in wholes):
            found.append("partial_quote")
    open_conditions = claim.get("open_conditions")
    if open_conditions:
        found.append("unmet_condition")
    return [{"code": code, "text": _TEXT[code]} for code in found]


def level_of(reason_rows: list[dict]) -> str:
    """No reason is solid, one is partial, two or more are thin."""
    return SOLID if not reason_rows else PARTIAL if len(reason_rows) == 1 else THIN


def assess(claim: Mapping) -> dict:
    """The `evidence` object of one claim row."""
    rows = reasons(claim)
    return {"level": level_of(rows), "reasons": rows}


def standing_of(source: Mapping) -> str | None:
    """Where a source stands for the reader: `trusted`, `neutral` or `low`.

    The same three words `tier_pages` gives a page Chat read, drawn from the
    same two engine numbers (`exactfind.TRUSTED_AT` and `LOW_TRUST_BELOW`), so
    a screen holds no list of sites and no threshold. `None` when nothing says
    how far the source is trusted: the chip then draws no mark, never a guess.
    """
    number = _trust(source)
    if number is None:
        return None
    from app import exactfind

    return "trusted" if number >= exactfind.TRUSTED_AT else "low" if number < LOW_TRUST_BELOW else "neutral"


def _stand(claim: Mapping) -> list | None:
    rows = claim.get("sources")
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows:
        if isinstance(row, Mapping) and "standing" not in row and (standing := standing_of(row)):
            row = {**row, "standing": standing}
        out.append(row)
    return out


def annotate(claims: Iterable[Mapping]) -> list[dict]:
    """The claim rows, each with its `evidence` object and each source's
    `standing`. Nothing else changes."""
    out = []
    for claim in claims:
        row = {**claim, "evidence": assess(claim)}
        if (sources := _stand(claim)) is not None:
            row["sources"] = sources
        out.append(row)
    return out


def tier_pages(activity: Iterable[Mapping] | None, question: str = "") -> list[dict]:
    """A turn's activity rows, with the kind of site behind each page it read.

    Adds `trust` (`exactfind.classify`: `domain`, `tier`, `label`, `trust`, and
    `standing`: `trusted`, `neutral` or `low`) to each `read` row and changes
    nothing else. The right-hand column of Chat draws a source's trust tier
    from this, so the tier and where it stands are the engine's and the screen
    holds no list of sites and no threshold. A row with no address is left as
    it was.
    """
    from app import exactfind

    out: list[dict] = []
    for row in activity or []:
        item = dict(row)
        url = str(item.get("url") or "")
        if item.get("kind") == "read" and url and "trust" not in item:
            try:
                found = exactfind.classify(url, question)
                number = float(found["trust"])
                standing = ("trusted" if exactfind.is_trusted(found)
                            else "low" if number < LOW_TRUST_BELOW else "neutral")
                item["trust"] = {**found, "standing": standing}
            except Exception:  # noqa: BLE001 - a missing registry never costs the turn
                pass
        out.append(item)
    return out
