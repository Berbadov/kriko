"""Check a list: a spreadsheet's worth of product names against the installed catalogs.

A buyer keeps the products they plan to buy in a sheet. One press should say
which rows have known problems, with no language model and no web. The window
reads the file and sends only the names; each name is matched here, in one
request, with the engine's own two readings of a name and nothing of its own:

* `find.by_name`: the catalog's product name sits inside the row's text
  ("Dell XPS 13 9310 16GB silver"); the longest name wins.
* `find.search`: every word of the row is on one product ("iphone 15 pro max").

A match is only ever returned when exactly one product fits. Two equally good
products, or a weak one, come back as `match: null` with the candidates in
`others`, because a guessed product tells the buyer about the wrong thing. No
make, model or category is named here: every word comes from the installed
catalogs, so a new catalog is covered by installing it.

What is said about a matched product is what its page says: the claims that
apply to it, counted by the engine's own severity words.
"""

import re
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints

from app.web.deps import get_store
from app.web.routers.subjects import _claims_for, _direct_claims
from kriko.lookup import find

router = APIRouter(prefix="/api", tags=["checklist"])

#: How many rows one request checks, and how long a name may be.
MAX_NAMES = 300
MAX_NAME_LENGTH = 200
#: How many candidates an ambiguous row offers.
MAX_OTHERS = 6

#: The engine's severity vocabulary as the reader's four words. Anything else
#: ("unrated") still counts in `total`, and is the reader's "To check".
_SERIOUS = ("critical", "high")
_KNOWN = ("medium",)
_MINOR = ("low",)
_ORDER = ("critical", "high", "medium", "low")


class CheckListRequest(BaseModel):
    names: list[Annotated[str, StringConstraints(max_length=MAX_NAME_LENGTH)]] = Field(
        min_length=1, max_length=MAX_NAMES)


def _words(text) -> frozenset[str]:
    plain = unicodedata.normalize("NFKD", str(text or "").casefold())
    folded = "".join(c for c in plain if not unicodedata.combining(c))
    return frozenset(re.findall(r"[a-z0-9]+", folded))


def _candidate(hit: dict) -> dict:
    return {"subject_id": hit["subject_id"], "pack_id": hit["pack_id"],
            "label": hit.get("label", "")}


def _distinct(hits: list[dict]) -> list[dict]:
    seen, out = set(), []
    for hit in hits:
        key = (hit["subject_id"], hit["pack_id"])
        if key not in seen:
            seen.add(key)
            out.append(hit)
    return out


def _resolve(store, name: str) -> tuple[dict | None, str, list[dict]]:
    """(the one product, how it was found, the candidates when several fit)."""
    typed = _words(name)
    if not typed:
        return None, "", []

    named = find.by_name(store, name, limit=50)
    if named:
        top = _distinct([h for h in named if h["score"] == named[0]["score"]])
        if len(top) == 1:
            hit = top[0]
            exact = any(_words(p) == typed for p in hit.get("why", []))
            return hit, "exact" if exact else "name", []
        return None, "", top[:MAX_OTHERS]

    found = _distinct(find.search(store, name, limit=find.LIMIT))
    if not found:
        return None, "", []
    if len(found) == 1:
        return found[0], "words", []
    # Several products hold every word. One of them is the answer only when
    # its own name is exactly what was typed.
    ids = [h["subject_id"] for h in found]
    aliases: dict[str, list[str]] = {}
    for row in store.execute(
        f"SELECT subject_id, alias FROM subject_aliases WHERE subject_id IN ({','.join('?' * len(ids))})",
        ids,
    ):
        aliases.setdefault(row["subject_id"], []).append(row["alias"])
    same = _distinct([
        h for h in found
        if _words(h.get("label")) == typed
        or any(_words(a) == typed for a in aliases.get(h["subject_id"], []))
    ])
    if len(same) == 1:
        return same[0], "exact", []
    return None, "", found[:MAX_OTHERS]


def _summary(store, hit: dict, cache: dict) -> dict:
    """The counts and the leading finding of one product, read once per request."""
    key = (hit["subject_id"], hit["pack_id"])
    if key in cache:
        return cache[key]
    row = {"subject_id": hit["subject_id"], "pack_id": hit["pack_id"],
           "kind": hit.get("kind", "product")}
    claims = _claims_for(store, row) or _direct_claims(store, hit["subject_id"])
    severities = [str(c.get("severity") or "").lower() for c in claims]
    counts = {
        "total": len(claims),
        "serious": sum(1 for s in severities if s in _SERIOUS),
        "known": sum(1 for s in severities if s in _KNOWN),
        "minor": sum(1 for s in severities if s in _MINOR),
    }
    leading = None
    for level in _ORDER:
        at = next((i for i, s in enumerate(severities) if s == level), None)
        if at is not None:
            leading = {"title": str(claims[at].get("title") or "").strip(), "severity": level}
            break
    cache[key] = {"claims": counts, "leading": leading}
    return cache[key]


@router.post("/check-list")
def check_list(body: CheckListRequest, store=Depends(get_store)) -> dict:
    """Each name matched and summarised. `index` is the position in `names`."""
    cache: dict = {}
    items = []
    for index, name in enumerate(body.names):
        query = " ".join(name.split())
        hit, how, others = _resolve(store, query)
        if hit is not None:
            summary = _summary(store, hit, cache)
            items.append({
                "index": index, "query": query,
                "match": {"subject_id": hit["subject_id"], "pack_id": hit["pack_id"],
                          "label": hit.get("label", ""), "confidence": how},
                **summary, "others": [],
            })
            continue
        items.append({
            "index": index, "query": query, "match": None,
            "claims": {"total": 0, "serious": 0, "known": 0, "minor": 0},
            "leading": None,
            # The candidates carry their own summary, so choosing one in the
            # window needs no second request.
            "others": [{**_candidate(o), **_summary(store, o, cache)} for o in others],
        })
    return {"items": items}
