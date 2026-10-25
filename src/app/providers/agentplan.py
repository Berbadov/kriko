"""What a research turn owes before it answers, as pure functions.

Kriko Agent spent the Settings dial the same way on every question, took any
page a search returned as evidence about the product, and kept a result for
fifteen minutes whatever it was about. This module is the small, deterministic
layer that fixes those three things without a model call and without knowing a
category:

- **plan**: which kinds of source the reader's own words ask for
  (`local_search_plan.choose_kinds`), and how many retrievals that question is
  worth. A question that asks only for a maker's figures or a review does not
  need the budget of one asking what goes wrong; a question that names nothing
  gets the dial untouched, so this fails open.
- **identity**: the words that make a page about *this* product — model codes
  and proper names pulled from the question — and whether a page's text carries
  them. It is a signal handed to the agent and kept in the record, never a gate:
  a page that fails it is flagged, not dropped.
- **freshness**: how long a result of each kind may be reused. A recall notice
  goes stale in minutes, a maker's manual in a day.
- **record**: what a turn did, in numbers and kinds, merged across the calls of
  one turn and carried to the reader's screen beside the answer.

The vocabularies here are the engine's closed ones: kinds of source and
function words. No product, make or model appears in this file.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.providers import local_search_plan
from app.providers.local_identity import fold

#: A question that asks only for these is a lookup, not a hunt for failures.
FAILURE_KINDS = ("forums", "recalls")
#: Retrievals a lookup question is worth, under whatever the dial allows.
LOOKUP_CALLS = 4
#: How many identity terms a question is reduced to.
MAX_IDENTITY_TERMS = 6

#: How long a result of each kind may be reused, in seconds. Where a source goes
#: stale is true of any category: an official notice in minutes, discussion in
#: half an hour, a maker's own documentation in a day.
FRESHNESS_SECONDS: dict[str, int] = {
    "recalls": 5 * 60,
    "news": 10 * 60,
    "forums": 30 * 60,
    "reviews": 60 * 60,
    "video": 60 * 60,
    "manufacturer": 24 * 60 * 60,
}

#: Function words that open or carry a question without naming anything. A
#: closed vocabulary of questions in the languages `local_search_plan` speaks.
_FUNCTION_WORDS = frozenset((
    "a an the and or of for to in on at with without about is are was were be do does did "
    "has have had can could will would should what which who whom whose when where why how "
    "tell show give find any some there this that these those it its my me you your i we "
    "problems problem issues issue known common worth buy buying review reviews recall recalls "
    "ne nedir nasil hangi kac mi mu var yok bu su bir ve ile icin gibi daha en cok "
    "quel quelle quels quelles est sont comment pourquoi le la les un une des du de et ou "
    "was wie warum welche welcher ist sind der die das ein eine und oder "
    "que cual cuales es son como por el los las una unos y o"
).split())

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Plan:
    """What the reader's question asks for, before any search is spent."""

    #: The kinds of source the question names, in the order a plan tries them.
    kinds: tuple[str, ...] = ()
    #: Retrievals worth spending: never above the dial's own ceiling.
    calls: int = 0
    #: Folded words that make a page about this product.
    identity: tuple[str, ...] = ()


def _is_code(word: str) -> bool:
    return any(c.isalpha() for c in word) and any(c.isdigit() for c in word)


def identity_terms(question: str, limit: int = MAX_IDENTITY_TERMS) -> tuple[str, ...]:
    """The words of a question that name the product, folded and in order.

    A model code (letters with digits) or a capitalised word that is not a
    question word. A bare number is not one: it is a price, a year or a count,
    and a page about a different product carries the same digits.
    """
    text = str(question or "")
    found: list[str] = []
    for match in _WORD.finditer(text):
        word = match.group()
        key = fold(word)
        before = text[:match.start()].rstrip()
        opens_sentence = not before or before[-1] in ".?!:;"
        # A capital in the middle of a sentence is a name ("Mi 11", so a function
        # word is let through there); a function word that opens one is grammar.
        if key in found or (key in _FUNCTION_WORDS and (opens_sentence or word[:1].islower())):
            continue
        named = len(word) > 1 and (any(c.isupper() for c in word[1:]) or word[:1].isupper())
        if (_is_code(word) or named) and not word.isdigit():
            found.append(key)
        if len(found) >= limit:
            break
    return tuple(found)


def mentions(identity: tuple[str, ...], text: str) -> bool | None:
    """Whether a page's text carries the product's own words.

    `None` when the question named nothing to look for, because "unknown" must
    not read as "different product". Model codes must all appear (spaces and
    hyphens ignored, since a page writes "Buds 2" as freely as "Buds2"); the
    plain names must mostly appear, as whole words.
    """
    if not identity:
        return None
    folded = fold(str(text or ""))
    squashed = re.sub(r"[\W_]+", "", folded)
    words = set(_WORD.findall(folded))
    codes = [term for term in identity if _is_code(term)]
    if codes:
        return all(code in squashed for code in codes)
    needed = math.ceil(len(identity) * 2 / 3)
    return sum(1 for term in identity if term in words) >= needed


def make_plan(question: str, *, ceiling: int) -> Plan:
    """The plan for one question under the dial's ceiling on retrievals."""
    ceiling = max(0, int(ceiling))
    kinds = tuple(local_search_plan.choose_kinds(question, limit=3))
    asks_failures = any(kind in FAILURE_KINDS for kind in kinds)
    lookup = bool(kinds) and not asks_failures and len(kinds) < 2
    return Plan(
        kinds=kinds,
        calls=min(ceiling, LOOKUP_CALLS) if lookup else ceiling,
        identity=identity_terms(question),
    )


def missing_kinds(plan: Plan, searched) -> list[str]:
    """The kinds the question asked for that no search has gone to yet."""
    return [kind for kind in plan.kinds if kind not in searched]


def coverage_hint(plan: Plan, searched, calls_left: int) -> dict:
    """What to hand the agent beside a round's results, or `{}` when nothing is owed.

    In-band on purpose: asking again after a finished draft costs a model call
    and throws away words the reader already watched stream in; a note beside
    the evidence is read before the agent decides to answer.
    """
    owed = missing_kinds(plan, searched)
    if not owed or calls_left <= 0:
        return {}
    return {
        "still_asked": [
            {"kind": kind, "for": local_search_plan.SOURCE_KINDS[kind],
             "word": local_search_plan.kind_marker(kind)}
            for kind in owed
        ],
        "retrievals_left": calls_left,
        "note": ("The question also asks for the kinds above. Search each once with its "
                 "word, or say plainly that you did not look there."),
    }


def search_ttl(kind: str, default: int) -> int:
    """How long a search result of this kind may be reused."""
    return FRESHNESS_SECONDS.get(kind, default)


# ── the record ───────────────────────────────────────────────────────────────

_COUNTS = ("searches", "pages", "unreadable", "cached", "retrieved")
_OPTIONAL_COUNTS = ("on_product", "off_product")


def build_record(*, searches: int, kinds, missing, pages: int, unreadable: int,
                 cached: int, retrieved: int, on_product: int | None = None,
                 off_product: int | None = None) -> dict:
    """One call's account of itself, in the shape the screens read.

    `on_product` and `off_product` are omitted unless the question named a
    product to check pages against: an absent key means "not checked".
    """
    record: dict = {
        "searches": int(searches), "pages": int(pages), "unreadable": int(unreadable),
        "cached": int(cached), "retrieved": int(retrieved),
        "kinds": _in_order(kinds), "missing": _in_order(missing),
    }
    if on_product is not None:
        record["on_product"] = int(on_product)
    if off_product is not None:
        record["off_product"] = int(off_product)
    return record


def _in_order(kinds) -> list[str]:
    wanted = {kind for kind in kinds or () if kind in local_search_plan.SOURCE_KINDS}
    return [kind for kind in local_search_plan.KIND_ORDER if kind in wanted]


def merge_records(first: dict | None, second: dict | None) -> dict:
    """Two calls of one turn as one record. Counts add; a kind covered by either
    call is covered, so it stops being missing."""
    first = first if isinstance(first, dict) else {}
    second = second if isinstance(second, dict) else {}
    if not first and not second:
        return {}
    merged: dict = {}
    for name in _COUNTS:
        merged[name] = _whole(first.get(name)) + _whole(second.get(name))
    for name in _OPTIONAL_COUNTS:
        if name in first or name in second:
            merged[name] = _whole(first.get(name)) + _whole(second.get(name))
    kinds = _in_order([*(first.get("kinds") or []), *(second.get("kinds") or [])])
    owed = _in_order([*(first.get("missing") or []), *(second.get("missing") or [])])
    merged["kinds"] = kinds
    merged["missing"] = [kind for kind in owed if kind not in kinds]
    return merged


def _whole(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def record_line(record: dict) -> str:
    """The record as one job-log line, so the log says what the screen will."""
    if not isinstance(record, dict) or not record:
        return ""
    parts = [f"{_whole(record.get('searches'))} search(es)",
             f"{_whole(record.get('pages'))} page(s) read"]
    if _whole(record.get("unreadable")):
        parts.append(f"{_whole(record['unreadable'])} unreadable")
    if "off_product" in record and _whole(record.get("off_product")):
        parts.append(f"{_whole(record['off_product'])} not about this product")
    kinds = record.get("kinds") or []
    if kinds:
        parts.append("kinds: " + ", ".join(kinds))
    if record.get("missing"):
        parts.append("not searched: " + ", ".join(record["missing"]))
    return "record: " + " · ".join(parts)
