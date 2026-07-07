"""Entity resolution: which component does this evidence describe?

Attribution comes from the evidence's OWN text against catalog-derived codes
(never from the search query that found the document — design_flaws.md
Flaw 1). target_hint participates only to disambiguate genuine multi-code
comparisons and as a last-resort fallback that the verdict call re-checks."""

import re
from functools import lru_cache
from pathlib import Path

import yaml

from knowledge.ledger import db  # noqa: F401  (shared connection conventions)
from knowledge.stoplists import (
    catalog_code_manufacturers, code_tokens, mentions_foreign_manufacturer_code,
)

RESOLVER_VERSION = 1
_PARTS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "parts"
_POWER_SUFFIX_RE = re.compile(r"_\d+$")
_SUFFIX_RE = re.compile(r"_.*$")  # Strip anything after underscore (domain/power suffix)


@lru_cache(maxsize=1)
def component_registry() -> dict[str, str]:
    """Uppercase CODE -> lowercase component id, derived from part YAMLs.

    Same derive-from-catalog pattern as stoplists.catalog_code_manufacturers:
    a new part is covered the moment its stub exists. Power-tune suffixes
    (ea888_220) collapse onto the engineering identity (ea888)."""
    reg: dict[str, str] = {}
    for path in _PARTS_DIR.glob("**/*.yaml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        part_id = data.get("part_id")
        if not part_id:
            continue
        base = _POWER_SUFFIX_RE.sub("", str(part_id))
        for code in code_tokens(base):
            reg[code] = base.lower()
    return reg


def _hint_components(target_hint: str, reg: dict[str, str]) -> set[str]:
    base = _SUFFIX_RE.sub("", target_hint or "")
    return {reg[t] for t in code_tokens(base) if t in reg}


def resolve_all(conn) -> dict[str, int]:
    reg = component_registry()
    counts = {"alias": 0, "foreign": 0, "hint": 0}
    rows = conn.execute(
        "SELECT e.id, e.title, e.rationale, e.quote, e.component_hint, d.target_hint"
        " FROM evidence e JOIN documents d ON d.id = e.doc_id"
        " LEFT JOIN resolutions r ON r.evidence_id = e.id"
        " WHERE r.evidence_id IS NULL ORDER BY e.id"
    ).fetchall()
    for row in rows:
        own_text = " ".join(filter(None, (
            row["title"], row["rationale"], row["quote"], row["component_hint"])))
        named = {reg[t] for t in code_tokens(own_text) if t in reg}
        hinted = _hint_components(row["target_hint"], reg)

        if len(named) == 1:
            comp, method = next(iter(named)), "alias"
        elif len(named) > 1:
            inter = named & hinted
            if len(inter) == 1:
                comp, method = next(iter(inter)), "alias"
            else:
                comp, method = "unresolved", "hint"
        else:
            own_makes: set[str] = set()
            for c in hinted:
                own_makes |= catalog_code_manufacturers().get(c.upper(), frozenset())
            if own_makes and mentions_foreign_manufacturer_code(own_text, own_makes):
                comp, method = "foreign", "foreign"
            elif len(hinted) == 1:
                comp, method = next(iter(hinted)), "hint"
            else:
                comp = (row["target_hint"] or "unresolved").lower() or "unresolved"
                method = "hint"

        conn.execute(
            "INSERT INTO resolutions (evidence_id, component_id, method,"
            " resolver_version) VALUES (?,?,?,?)",
            (row["id"], comp, method, RESOLVER_VERSION),
        )
        counts[method] += 1
    conn.commit()
    return counts
