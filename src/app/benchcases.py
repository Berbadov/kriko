"""The benchmark's fixed test set (B185, decision D6).

The reader's sentence this exists for: "Use fixed tests, not the user's
installed packs (packs are made with agents anyway)".

A benchmark whose cases come from the installed store measures whatever
happens to be installed, so two machines, or one machine before and after
reinstalling, never measured the same thing and could not be compared.
The reader's own packs are also exactly what the benchmark should *not*
score: packs are drafted by the same agents the benchmark is judging.

So the set ships with the app, versioned in one file. A run records the
`set_id` and `set_version` it measured, and results from different sets are
never ranked together (see `bench.readout`).

Each case is a product with ground truth: what a competent run should find,
what it must not claim, and the search queries that reach the sources. The
products are deliberately ordinary and span more than one category, so the
set cannot be read as being about any pack.
"""

import json
import pathlib

#: The set's own identity, recorded on every run that measures it.
SET_ID = "kriko-fixed"
SET_VERSION = "2026.10.1"

#: Where the set ships. Beside this module, one file, so a new set is a
#: version bump plus a diff a reviewer can read.
_FILE = pathlib.Path(__file__).with_name("benchcases.json")

#: The questions a case asks, once each. "fixed" is its own kind, so a row
#: measured on the fixed set is never averaged into a pack-derived one.
KIND = "fixed"


def load() -> list[dict]:
    """Every case in the set, in file order.

    In file order on purpose: the set is versioned, and a stable order is
    part of what the version promises. `limit` is the caller's, applied
    after, so "the first three" is the same three on every machine.
    """
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cases = []
    for one in raw.get("cases", []):
        if not isinstance(one, dict):
            continue
        name = str(one.get("product") or "").strip()
        if not name:
            continue
        cases.append({
            "id": str(one.get("id") or name.lower().replace(" ", "-")),
            "kind": KIND,
            "product": name,
            "queries": [str(q).strip() for q in (one.get("queries") or [])
                        if str(q).strip()],
            "must_find": [
                {"claim": str(entry.get("claim", "")).strip(),
                 "domain": str(entry.get("domain", "")).strip(),
                 "quote": str(entry.get("quote", "")).strip()}
                for entry in (one.get("must_find") or [])
                if str(entry.get("claim", "")).strip()
            ],
            "must_not_find": [
                {"claim": str(entry.get("claim", "")).strip(),
                 "why": str(entry.get("why", "")).strip()}
                for entry in (one.get("must_not_find") or [])
                if str(entry.get("claim", "")).strip()
            ],
            "known_absent": [str(x).strip() for x in (one.get("known_absent") or [])
                             if str(x).strip()],
        })
    return cases


def case_rows(limit: int) -> list[dict]:
    """The first `limit` cases, each stamped with the set's identity."""
    found = load()[: max(1, min(limit, 50))]
    for case in found:
        case["set_id"] = SET_ID
        case["set_version"] = SET_VERSION
    return found
