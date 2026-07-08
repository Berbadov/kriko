"""Entity resolution: which component does this evidence describe?

Attribution comes from the evidence's OWN text against catalog-derived codes
(never from the search query that found the document — design_flaws.md
Flaw 1). target_hint participates only to disambiguate genuine multi-code
comparisons and as a last-resort fallback that the verdict call re-checks."""

import re
from functools import lru_cache
from pathlib import Path

import yaml

# resolve_all() operates on a db.connect() connection passed in by the caller.
from knowledge.stoplists import (
    catalog_code_manufacturers, code_tokens, mentions_foreign_manufacturer_code,
)

RESOLVER_VERSION = 1
_PARTS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "parts"
_POWER_SUFFIX_RE = re.compile(r"_\d+$")
_SUFFIX_RE = re.compile(r"_.*$")  # Strip anything after underscore (domain/power suffix)


def _iter_part_ids():
    """part_id strings straight off every part YAML — the single catalog read
    both component_registry() and known_part_ids() derive from."""
    for path in _PARTS_DIR.glob("**/*.yaml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        part_id = data.get("part_id")
        if part_id:
            yield str(part_id)


@lru_cache(maxsize=1)
def component_registry() -> dict[str, str]:
    """Uppercase engine/gearbox CODE -> lowercase component id, derived from
    part YAMLs.

    Same derive-from-catalog pattern as stoplists.catalog_code_manufacturers:
    a new part is covered the moment its stub exists. Power-tune suffixes
    (ea888_220) collapse onto the engineering identity (ea888). Parts keyed by
    model rather than a code (body/electrical stubs like golf7_body) carry no
    code_tokens match and so never enter here — they resolve through the hint
    path via known_part_ids() instead."""
    reg: dict[str, str] = {}
    for part_id in _iter_part_ids():
        base = _POWER_SUFFIX_RE.sub("", part_id)
        for code in code_tokens(base):
            reg[code] = base.lower()
    return reg


@lru_cache(maxsize=1)
def known_part_ids() -> frozenset[str]:
    """Every catalog part_id in the same power-collapsed, lowercase form
    component_registry() emits its values in. Lets the hint fallback recover
    the real component for parts that carry no engine/gearbox code and so never
    enter the code registry (body/electrical stubs keyed by model, e.g.
    golf7_body, which code_tokens cannot tokenize)."""
    return frozenset(_POWER_SUFFIX_RE.sub("", pid).lower() for pid in _iter_part_ids())


def _hint_part_id(target_hint: str) -> str | None:
    """The longest known part_id the hint names — hint == pid or hint starts
    with pid + '_'. Recovers 'megane4_elec' from the ingest-produced hint
    'megane4_elec_electrical' and 'h4d' from 'h4d_75_engine', instead of the
    string-mangling that stored a domain-suffixed non-component id."""
    h = (target_hint or "").lower()
    best: str | None = None
    for pid in known_part_ids():
        if (h == pid or h.startswith(pid + "_")) and (best is None or len(pid) > len(best)):
            best = pid
    return best


def _hint_components(target_hint: str, reg: dict[str, str]) -> set[str]:
    base = _SUFFIX_RE.sub("", target_hint or "")
    comps = {reg[t] for t in code_tokens(base) if t in reg}
    if not comps:
        pid = _hint_part_id(target_hint)
        if pid:
            comps = {pid}
    return comps


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
        hint_makes: set[str] = set()
        for c in hinted:
            hint_makes |= catalog_code_manufacturers().get(c.upper(), frozenset())

        # Contamination guard must precede aliasing: the own-text code we'd
        # otherwise alias to may itself be the foreign mention (a Renault K9K
        # named in a doc discovered under a VW gearbox hint — design_flaws.md
        # Flaw 1). Every catalog code is in `reg`, so if this ran only when
        # `named` were empty it could never fire. Same-manufacturer reroutes
        # (DQ200 under a DQ381 hint, both VW) are not foreign and still alias.
        if hint_makes and mentions_foreign_manufacturer_code(own_text, hint_makes):
            comp, method = "foreign", "foreign"
        elif len(named) == 1:
            comp, method = next(iter(named)), "alias"
        elif len(named) > 1:
            inter = named & hinted
            if len(inter) == 1:
                comp, method = next(iter(inter)), "alias"
            else:
                comp, method = "unresolved", "hint"
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
