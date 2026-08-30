"""Turning a scraped page into a query, using rules a pack supplies.

A listing site says "Motor Hacmi: 1.461 cm3". The engine needs
`displacement_cc = 1461`. The mapping between those is category knowledge and
site knowledge, and neither belongs in Python here — a pack ships it as JSON.

**The rules are data and are interpreted here, never executed in the browser.**
That is a security boundary, not a style preference. If a pack could ship
JavaScript into a content script, installing a pack would mean granting its
author the ability to run code on every page the extension can see. So the
adapter format is a fixed vocabulary of label lists and parse hints, and
anything it cannot express is a reason to extend this file — in review, once —
rather than to open that door.

The parse hints exist because scraped values lie in a specific way. A page might
render mileage as "148.000 km" and engine size as "1.461 cm3"; the same digits
mean a hundred and forty-eight thousand in one and one thousand four hundred
sixty-one in the other. Range bounds resolve that: a value that lands outside
the plausible range for its field is discarded rather than believed, because a
wrong number is worse than a missing one — a missing one fails open and says so.
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


def load_adapters(conn, pack_ids=None) -> list[dict]:
    """Every adapter shipped by the enabled packs."""
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
        spec["pack_id"] = row["pack_id"]
        out.append(spec)
    return out


def adapter_for(conn, url: str, pack_ids=None) -> dict | None:
    for spec in load_adapters(conn, pack_ids):
        if any(_glob_match(p, url) for p in spec.get("match", [])):
            return spec
    return None


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
    # A page often packs several facts into one cell — "DSG / 7 Gear / Front
    # Wheel Drive" is a gearbox, a gear count and a drivetrain. Naming an end
    # of the split is the whole vocabulary on purpose: anything richer becomes
    # a small programming language shipped by pack authors, which is the door
    # this module exists to keep shut.
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

    Exact labels go first because a page that lists both "Yakıt Tüketimi"
    (consumption) and "Yakıt" (fuel type) would otherwise be answered by
    whichever came first in the DOM, and half the time the engine would be
    told the car runs on "4,5 lt".

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
