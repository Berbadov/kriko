"""Turning a scraped page into a query, using rules a pack supplies.

A listing site labels each field in its own words and its own units. Mapping
a label to an attribute key and a value is category knowledge and site
knowledge, and neither belongs in Python here — a pack ships it as JSON.

**The rules are data and are interpreted here, never executed in the browser.**
That is a security boundary, not a style preference. If a pack could ship
JavaScript into a content script, installing a pack would mean granting its
author the ability to run code on every page the extension can see. So the
adapter format is a fixed vocabulary of label lists and parse hints, and
anything it cannot express is a reason to extend this file — in review, once —
rather than to open that door.

The parse hints exist because scraped values lie in a specific way: a
locale's own number formatting is ambiguous out of context. One instance a
pack has to handle is mileage rendered as "148.000 km" — a period used as the
thousands separator, not a decimal point, so the raw digits mean a hundred
and forty-eight thousand rather than one hundred forty-eight point zero.
Range bounds resolve that: a value that lands outside the plausible range for
its field is discarded rather than believed, because a wrong number is worse
than a missing one — a missing one fails open and says so.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

_DIGITS = re.compile(r"\d[\d.,\s]*")


@dataclass(frozen=True)
class Adapted:
    adapter_id: str
    kind: str
    identity: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    #: Labels the page had that the adapter has no rule for. Not an error — a
    #: coverage signal, so a site adding a useful field is discoverable instead
    #: of silently ignored forever.
    unmapped: tuple[str, ...] = ()


def _glob_match(pattern: str, url: str) -> bool:
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.fullmatch(escaped, url, re.IGNORECASE) is not None


def load_adapters(conn, pack_ids=None, *, any_site: bool = False) -> list[dict]:
    """Every adapter shipped by the enabled packs.

    Host adapters by default. An **any-site** adapter (`"any_site": true`)
    reads the structured product data a page publishes for search engines
    rather than one site's markup, so it has no `match` and must never be
    listed as a site Kriko reads — it is asked only after every host adapter
    has declined (B149). `any_site=True` returns those instead.
    """
    rows = conn.execute(
        "SELECT a.pack_id, a.name, a.content FROM pack_assets a"
        " JOIN packs p USING (pack_id)"
        " WHERE a.kind = 'adapter' AND p.enabled = 1")
    out = []
    for row in rows:
        if pack_ids and row["pack_id"] not in pack_ids:
            continue
        try:
            spec = json.loads(row["content"])
        except json.JSONDecodeError:
            continue        # a broken adapter must not break every other site
        if not isinstance(spec, dict) or bool(spec.get("any_site")) != any_site:
            continue
        spec["pack_id"] = row["pack_id"]
        out.append(spec)
    return out


def adapter_for(conn, url: str, pack_ids=None) -> dict | None:
    found = adapters_for(conn, url, pack_ids)
    return found[0] if found else None


def adapters_for(conn, url: str, pack_ids=None) -> list[dict]:
    """Every host adapter whose pattern matches `url`, in pack order.

    More than one is ordinary: any pack may ship a reader for a site its
    products are sold on, and a marketplace sells everything. Which of them
    actually reads *this* page is `best_reading`'s question, asked with the
    page in hand — the first match by pack id is not an answer (B150: an
    agent-written pack's reader for one category was reading every product
    of another category on its site).
    """
    return [spec for spec in load_adapters(conn, pack_ids)
            if any(_glob_match(p, url) for p in spec.get("match", []))]


def _fold(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def best_reading(conn, specs: list[dict], fields: dict, *, url: str = "",
                 title: str = "", description: str = "",
                 vocabulary: dict | None = None):
    """The one of several adapters that reads this page best, as `(spec, mapped)`.

    Each reads the page; the winner is the reading whose identity values its
    *own* pack already holds (one pack's reader finds a "brand" on another
    category's page, but not one its own pack knows), then the one that read the
    most identity and context keys. A tie keeps the order given, so the same
    page lands on the same reader every visit. None for no specs.
    """
    best, best_score = None, None
    own: dict[str, dict] = {}
    for spec in specs:
        mapped = adapt(spec, fields, url=url, title=title,
                       description=description, vocabulary=vocabulary)
        pack = spec.get("pack_id", "")
        if pack not in own:
            own[pack] = {key: {_fold(v) for v in values} for key, values in
                         identity_vocabulary(conn, [pack] if pack else None).items()}
        known = sum(1 for key, value in mapped.identity.items()
                    if _fold(value) in own[pack].get(key, ()))
        score = (known, len(mapped.identity) + len(mapped.context))
        if best_score is None or score > best_score:
            best, best_score = (spec, mapped), score
    return best


def _number(raw: str, low=None, high=None):
    """First plausible number in a scraped string, or None.

    Separators are stripped rather than interpreted, because a page may use
    either convention and often both. The range check is what makes that safe:
    "1.461 cm3" and "148.000 km" both become bare digits, and only the one that
    falls inside its field's bounds survives.
    """
    for chunk in _DIGITS.findall(str(raw)):
        cleaned = re.sub(r"[.,\s]", "", chunk)
        if not cleaned:
            continue
        value = int(cleaned)
        if low is not None and value < low:
            continue
        if high is not None and value > high:
            continue
        return value
    return None


def _apply(rule: dict, raw):
    if rule.get("parse") == "int_range":
        return _number(raw, rule.get("min"), rule.get("max"))

    text = str(raw).strip()
    # A page often packs several facts into one cell — three attributes
    # separated by slashes, say. Naming an end of the split is the whole
    # vocabulary on purpose: anything richer becomes a small programming
    # language shipped by pack authors, which is the door this module exists
    # to keep shut.
    segment = rule.get("segment")
    if segment in ("first", "last"):
        parts = [p.strip() for p in text.split(rule.get("split", "/"))]
        parts = [p for p in parts if p]
        if parts:
            text = parts[0] if segment == "first" else parts[-1]

    return text or None


def _key(label) -> str:
    """A label reduced to something two people would agree is the same label.

    Case and a trailing colon are the obvious half. Combining marks are the
    half that bites: Turkish "İ" casefolds to "i" plus a combining dot, so
    "İlan No" and "ilan no" are different strings and a pack author has no way
    to see why their rule never fires. Stripping the marks is why the adapter
    no longer needs to carry "motor gücü" and "motor gucu" as separate labels.

    Only *marks* are dropped, never letters. "ı" is a letter in Turkish rather
    than an "i" with the dot removed, and it decomposes to nothing, so "yakıt"
    and "yakit" stay distinct — correctly.
    """
    folded = unicodedata.normalize("NFKD", str(label).casefold())
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", stripped).strip().rstrip(":").strip()


def identity_vocabulary(conn, pack_ids=None) -> dict[str, set[str]]:
    """Every value the installed packs treat as identity, keyed by attribute.

    This is what lets an adapter read a make out of a page title without any
    make ever being written down in this file or in the pack's JSON. The
    values are the pack's own `is_identity` rows, so coverage arrives with the
    data: onboarding a model makes its make readable, and a category nobody
    has imagined yet works the same way. A hand-kept list would be one more
    edit to forget — the failure mode CLAUDE.md's scalability principle is
    about.
    """
    sql = ("SELECT DISTINCT a.pack_id, a.key, a.value_text FROM attributes a"
           " JOIN packs p USING (pack_id)"
           " WHERE a.is_identity = 1 AND p.enabled = 1")
    out: dict[str, set[str]] = {}
    for row in conn.execute(sql):
        if pack_ids and row["pack_id"] not in pack_ids:
            continue
        out.setdefault(row["key"], set()).add(row["value_text"])
    return out


def _from_vocabulary(rule: dict, text: str, vocabulary: dict) -> str | None:
    """The longest known value of this attribute occurring in `text`.

    Longest-first because "Land Rover" contains "Rover"; taking the first hit
    would answer with the wrong make on exactly the listings where the title
    is all we have.
    """
    values = vocabulary.get(rule["vocabulary"]) or ()
    hay = f" {re.sub(r'[^a-z0-9]+', ' ', str(text).casefold())} "
    for value in sorted(values, key=len, reverse=True):
        needle = f" {re.sub(r'[^a-z0-9]+', ' ', str(value).casefold()).strip()} "
        if needle.strip() and needle in hay:
            return value
    return None


def declared_labels(spec: dict) -> list[str]:
    """Every label this adapter has an opinion about, ignored ones included.

    The content script uses these to find fields on a page whose markup it no
    longer recognises. Ignored labels belong in the list because the client
    must be able to *see* a label in order to report it — deciding that one
    means nothing is the server's job, and keeping that decision here is what
    stops it drifting into two places.
    """
    labels = {
        _key(label)
        for group in ("identity", "context")
        for rule in (spec.get(group) or {}).values()
        for label in rule.get("labels", [])
    } | {_key(label) for label in spec.get("ignore_labels", [])}
    return sorted(labels)


def _pick(rule: dict, fields: dict, extras: dict, blocked: frozenset = frozenset(),
          vocabulary: dict | None = None):
    """The value one rule claims off the page, or None.

    Three sources, tried in order of how much the page actually committed to
    the answer: an exact label, a loose label, then a text fallback.

    Exact labels go first because a page can carry two labels where one is a
    substring of the other — a rate, and the quantity it is a rate of, say —
    and loose matching would answer with whichever came first in the DOM,
    silently confident it had the right one.

    The text fallback exists because the info list is a single point of
    failure: this site has redesigned that markup repeatedly, and every
    redesign silently zeroed every field while the client went on reporting
    success. Reading the title is worse evidence than a label, so it is only
    consulted when no label answered.
    """
    labels = rule.get("labels") or []
    if labels:
        wanted = [_key(label) for label in labels]
        candidates = [(_key(label), value) for label, value in fields.items()]
        candidates = [(k, v) for k, v in candidates if k not in blocked]

        for match in (lambda w, k: w == k, lambda w, k: w in k):
            for key, value in candidates:
                if any(match(w, key) for w in wanted):
                    got = _apply(rule, value)
                    # `known`: the label's value counts only as a value the
                    # packs already hold (B149). An any-site page labels its
                    # brand whatever the product is; without this a page of
                    # another category reads as this pack's product, under a
                    # brand the pack has never heard of.
                    if got is not None and rule.get("known") and rule.get("vocabulary"):
                        got = _from_vocabulary(rule, got, vocabulary or {})
                    if got is not None:
                        return got

    source = rule.get("from")
    if source:
        text = extras.get(source, "")
        if rule.get("vocabulary"):
            return _from_vocabulary(rule, text, vocabulary or {})
        return _apply(rule, text)
    return None


def adapt(spec: dict, fields: dict, *, url: str = "", title: str = "",
          description: str = "", vocabulary: dict | None = None) -> Adapted:
    """Map one scraped page onto an identity and a context."""
    extras = {"title": title, "description": description, "url": url}

    # A blocklist, not just a reporting filter: a label the pack has declared
    # meaningless must not be *read*, or the only thing standing between a
    # near-miss label and the engine is whether a better label happened to be
    # on the page too.
    blocked = frozenset(_key(label) for label in spec.get("ignore_labels", []))

    identity, context = {}, {}
    for key, rule in (spec.get("identity") or {}).items():
        got = _pick(rule, fields, extras, blocked, vocabulary)
        if got is not None:
            identity[key] = got
    for key, rule in (spec.get("context") or {}).items():
        got = _pick(rule, fields, extras, blocked, vocabulary)
        if got is not None:
            context[key] = got

    for rule in spec.get("derive") or []:
        if rule.get("op") == "years_since":
            year = context.get(rule["from"]) or identity.get(rule["from"])
            if isinstance(year, int):
                context[rule["key"]] = max(0, date.today().year - year)

    known = {
        _key(label)
        for group in ("identity", "context")
        for rule in (spec.get(group) or {}).values()
        for label in rule.get("labels", [])
    } | {_key(label) for label in spec.get("ignore_labels", [])}

    unmapped = tuple(sorted(
        str(label) for label in fields
        if not any(k == _key(label) or k in _key(label) for k in known)))

    return Adapted(adapter_id=spec.get("id", "?"),
                   kind=spec.get("subject_kind", "product"),
                   identity=identity, context=context, unmapped=unmapped)


def adapt_any_site(conn, fields: dict, *, url: str = "", title: str = "",
                   description: str = "", vocabulary: dict | None = None):
    """The best any-site reading of a page, or None when no pack claims it.

    Every pack's any-site adapter reads the page; one counts only when it read
    every key its `requires` names. That is the whole guard against a page of
    one category being read as another's product: a pack requires identity
    values its own vocabulary knows, and a foreign page carries none. Among readings
    that qualify, the one that read the most identity wins, then the first
    pack by id so the answer does not reshuffle between two visits.
    """
    best = None
    for spec in sorted(load_adapters(conn, any_site=True),
                       key=lambda one: (one.get("pack_id", ""), one.get("id", ""))):
        # `page_types`: the schema.org types this pack's products publish as.
        # The first gate, before any label is read — a toy's shop page is a
        # plain Product, whatever real thing its title names.
        wanted = {str(t).casefold() for t in spec.get("page_types") or ()}
        if wanted and str(fields.get("ld:@type", "")).casefold() not in wanted:
            continue
        mapped = adapt(spec, fields, url=url, title=title,
                       description=description, vocabulary=vocabulary)
        if not mapped.identity:
            continue
        if any(key not in mapped.identity for key in spec.get("requires") or ()):
            continue
        if best is None or len(mapped.identity) > len(best[1].identity):
            best = (spec, mapped)
    return best


def local_panel(spec: dict) -> dict:
    """The panel this adapter declares for the reader's own page, or nothing.

    Returned opaque on purpose. The block describes markup on someone else's
    site and words in someone else's language, and this module is not allowed
    to know either — validating its shape here would mean writing that shape
    down in the engine, which is the same mistake as writing the words down in
    the browser. The interpreter is the extension; a block it cannot read
    renders nothing, which is what an absent block does too.
    """
    block = spec.get("local_panel")
    return block if isinstance(block, dict) else {}
