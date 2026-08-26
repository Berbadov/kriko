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
    return text or None


def _pick(rule: dict, fields: dict, extras: dict):
    source = rule.get("from")
    if source:
        return _apply(rule, extras.get(source, ""))

    wanted = [str(label).casefold() for label in rule.get("labels", [])]
    for label, value in fields.items():
        key = str(label).casefold().strip().rstrip(":")
        if any(w == key or w in key for w in wanted):
            got = _apply(rule, value)
            if got is not None:
                return got
    return None


def adapt(spec: dict, fields: dict, *, url: str = "", title: str = "",
          description: str = "") -> Adapted:
    """Map one scraped page onto an identity and a context."""
    extras = {"title": title, "description": description, "url": url}

    identity, context = {}, {}
    for key, rule in (spec.get("identity") or {}).items():
        got = _pick(rule, fields, extras)
        if got is not None:
            identity[key] = got
    for key, rule in (spec.get("context") or {}).items():
        got = _pick(rule, fields, extras)
        if got is not None:
            context[key] = got

    for rule in spec.get("derive") or []:
        if rule.get("op") == "years_since":
            year = context.get(rule["from"]) or identity.get(rule["from"])
            if isinstance(year, int):
                context[rule["key"]] = max(0, date.today().year - year)

    known = {
        label.casefold()
        for group in ("identity", "context")
        for rule in (spec.get(group) or {}).values()
        for label in rule.get("labels", [])
    } | {label.casefold() for label in spec.get("ignore_labels", [])}

    unmapped = tuple(sorted(
        str(label) for label in fields
        if not any(k == str(label).casefold().strip().rstrip(":")
                   or k in str(label).casefold() for k in known)))

    return Adapted(adapter_id=spec.get("id", "?"),
                   kind=spec.get("subject_kind", "product"),
                   identity=identity, context=context, unmapped=unmapped)
