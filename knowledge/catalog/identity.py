"""Variant identity — the one place that decides what makes two cars *different*.

Kriko identifies a car by its **powertrain**, never by its trim name: a listing
gives us make, model, year, fuel, displacement, power and gearbox, and nothing
else. Two catalog rows that agree on all of those are indistinguishable at
match time, so shipping both is not "more coverage" — it is an unresolvable
ambiguity the matcher can never narrow (see `backend/core/matcher.py`).

That rule used to live only in `backend/tests/test_catalog.py`, i.e. it was a
CI gate and nothing else. The agent onboarding path (B23) therefore *accepted*
a Golf 8 lineup keyed on marketing trims — Impression / Life / Style / R-Line —
wrote four rows describing two powertrains, reported success to the agent, and
the breakage surfaced hours later in a test the agent never runs. This module
is that rule promoted to a mechanism:

  * `find_overlaps` — the CI gate (test_catalog.py now imports it from here).
  * `collapse_duplicates` — the *fix*: powertrain-identical rows merge into one
    row before anything is written, so the ambiguity cannot be created.
  * `canonical_code` / `code_errors` — part codes must be real unit codes
    (`dq381`, `h5h`), not marketing descriptions (`7-speed DSG`), because a
    code is what a part file is named after and what a claim is attributed to.
    A family descriptor shared by siblings ("DSG") is an attribution hazard —
    `docs/design_flaws.md` Flaw 3.
  * `canonical_variant_id` — the id is derived from the powertrain, so it
    cannot encode a trim name in the first place.

Nothing here enumerates a make, model or code: the vocabularies are closed
engineering categories (transmission technologies, descriptor words), and the
known-code check reads the catalog on disk (CLAUDE.md scalability rule).
"""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "packs" / "cars" / "data"

# Matching tolerances — mirrored from backend/core/matcher.py. Two rows inside
# these bands are the same car as far as an ad can tell.
CC_TOLERANCE = 100
POWER_TOLERANCE = 5

# Pairs that genuinely collide within tolerance and have no catalog fix: real,
# closely-spaced tunes of one engine code where no field can narrow them. The
# matcher's designed-for-this ambiguous-match fallback (serve the union of both
# candidates' claims) is correct there, so they are not defects. Add an entry
# only after confirming no available field (transmission, engine_code, …)
# distinguishes the pair — otherwise the fix is a catalog fix.
ACCEPTED_OVERLAPS: frozenset[frozenset[str]] = frozenset({
    frozenset({"clio5_k9k_85", "clio5_k9k_100"}),  # Blue dCi 85 vs 100 — same
    # engine code, manual-only both, no field distinguishes an ad reporting hp
    # in the 85-95 range; matcher.py tol=10 genuinely can't tell them apart.
})

# ── Code vocabulary ──────────────────────────────────────────────────────────
#
# Closed engineering vocabulary (CLAUDE.md's stated exception): these are
# transmission *technologies* and marketing descriptors, not car-coverage data.
# They do not grow when a model is onboarded.

# Descriptors a researcher reaches for when they could not find the real unit
# code. Each is shared by several distinct gearboxes, so attributing a claim to
# one would spray it across siblings.
TRANSMISSION_DESCRIPTORS: frozenset[str] = frozenset({
    "dsg", "dct", "dkg", "edc", "cvt", "at", "mt", "amt", "automatic", "auto",
    "manual_transmission", "tiptronic", "s_tronic", "stronic", "powershift",
    "steptronic", "multitronic", "torque_converter", "dual_clutch",
    "automated_manual", "semi_automatic", "efficient_dynamics",
})

# Words that make a value a description rather than a code.
_DESCRIPTOR_WORDS = ("speed", "gear", "clutch", "auto", "manual", "trim",
                     "line", "edition", "package")

_CODE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")

# The pseudo-code the catalog uses for "no researchable gearbox part": manual
# boxes are not researched as parts (their failures are exactly what the
# ekspertiz test-drive catches — the product principle).
MANUAL_CODE = "manual"


def canonical_code(value: str | None) -> str:
    """Normalize a part code to catalog form: lowercase, `_`-separated.

    `"7-speed DSG"` -> `"7_speed_dsg"`, `"EA211_evo2"` -> `"ea211_evo2"`.
    Normalization alone does not make a value *valid* — see `code_errors`.
    """
    s = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return s.strip("_")


def code_errors(field: str, code: str, transmission: str | None = None) -> list[str]:
    """Why this value is not usable as a part code, if it isn't.

    A part code names a physical unit that gets its own research file and owns
    the claims attributed to it. Three things disqualify a value, all decidable
    without knowing anything about the specific car:

    1. It reads as a description (`7_speed_dsg`, `6_speed_manual`) — a code
       never starts with a digit and never contains "speed"/"gear"/"clutch".
    2. It is a technology descriptor shared by siblings (`dsg`, `edc`, `cvt`)
       — attributing a claim to it contaminates every sibling gearbox.
    3. It is not code-shaped at all (punctuation, spaces after normalizing).

    Manual gearboxes are the exception: they are not researched as parts, so
    any manual-ish value is normalized to `manual` rather than rejected.
    """
    if not code:
        return [f"{field}: empty"]
    if transmission == "manual" and (code == MANUAL_CODE or is_manualish(code)):
        return []
    errors = []
    if code[0].isdigit():
        errors.append(
            f"{field}: {code!r} looks like a description, not a unit code — "
            f"research the actual gearbox/engine code (e.g. dq381, dc4, h5h)")
    elif any(w in code for w in _DESCRIPTOR_WORDS):
        errors.append(
            f"{field}: {code!r} contains a marketing description — a part code "
            f"names the physical unit (e.g. dq200, ea888, k9k)")
    elif code in TRANSMISSION_DESCRIPTORS:
        errors.append(
            f"{field}: {code!r} is a technology family shared by several "
            f"different gearboxes — claims attributed to it would contaminate "
            f"its siblings. Give the specific unit code (dq200 vs dq250 vs "
            f"dq381), or omit the row until you can source it")
    elif not _CODE_RE.match(code):
        errors.append(f"{field}: {code!r} is not a code-shaped identifier")
    return errors


def is_manualish(code: str) -> bool:
    """Does this value describe a manual gearbox rather than name a unit?

    `6mt`, `5_speed_manual`, `manual_transmission` — all of which the catalog
    files as the `manual` pseudo-code, because manual boxes have no part file.
    """
    c = canonical_code(code)
    return bool(re.fullmatch(r"\d?_?\d*_?(speed_)?m(anual)?t?", c)
                or c in {"manual", "manual_transmission", "mt"})


def known_part_codes(data_dir: Path | None = None) -> set[str]:
    """Every part code the catalog already has a file for.

    Catalog-derived, never hand-listed: a new part is known the moment its
    stub exists (`knowledge/stoplists.py::catalog_code_manufacturers` pattern).
    """
    parts = (data_dir or DATA_DIR) / "parts"
    return {p.stem for p in parts.rglob("*.yaml")} if parts.exists() else set()


# ── Powertrain identity ──────────────────────────────────────────────────────


def _years(row: dict) -> range:
    return range(row["year_from"], (row.get("year_to") or 2099) + 1)


def _cc_overlaps(a: dict, b: dict, tol: int = CC_TOLERANCE) -> bool:
    """True when the rows' displacements are within matching tolerance.

    An unknown cc is conservatively treated as overlapping: a row that cannot
    state its displacement cannot claim to be distinguishable by it.
    """
    if not a.get("displacement_cc") or not b.get("displacement_cc"):
        return True
    return abs(a["displacement_cc"] - b["displacement_cc"]) <= tol


def _power_overlaps(a: dict, b: dict, tol: int = POWER_TOLERANCE) -> bool:
    a_min = (a.get("power_min_hp") or 0) - tol
    a_max = (a.get("power_max_hp") or 999) + tol
    b_min = (b.get("power_min_hp") or 0) - tol
    b_max = (b.get("power_max_hp") or 999) + tol
    return a_min <= b_max and b_min <= a_max


def _transmission_disambiguates(a: dict, b: dict) -> bool:
    """True when the ad's own manual/automatic wording can pick a winner.

    Mirrors matcher.py's `_narrow_by_transmission`: distinct, populated
    `transmission` values make a cc+power collision resolvable, so it is not a
    true overlap.
    """
    ta, tb = a.get("transmission"), b.get("transmission")
    return bool(ta) and bool(tb) and ta != tb


def indistinguishable(a: dict, b: dict) -> bool:
    """Would a listing be unable to tell these two rows apart?

    The exact predicate the matcher faces: same make/model/fuel, overlapping
    years, no transmission split, and cc+power inside tolerance.
    """
    if (a.get("make"), a.get("model"), a.get("fuel")) != \
       (b.get("make"), b.get("model"), b.get("fuel")):
        return False
    if not set(_years(a)) & set(_years(b)):
        return False
    if _transmission_disambiguates(a, b):
        return False
    return _cc_overlaps(a, b) and _power_overlaps(a, b)


def find_overlaps(variants: list[dict]) -> list[str]:
    """Human-readable description of every unresolvable pair in a catalog.

    The CI gate (`backend/tests/test_catalog.py`) and the agent write gate
    (`write_variants.validate_trims`) both call this — one rule, so the agent
    is told at submit time exactly what CI would have told it later.
    """
    errors = []
    for a, b in combinations(variants, 2):
        if not indistinguishable(a, b):
            continue
        if frozenset({a["id"], b["id"]}) in ACCEPTED_OVERLAPS:
            continue
        shared = sorted(set(_years(a)) & set(_years(b)))[:3]
        errors.append(
            f"OVERLAP: {a['id']} and {b['id']} share "
            f"({a['make']}, {a['model']}, {a['fuel']}, years {shared}…) "
            f"and both have overlapping cc ({a.get('displacement_cc')} vs "
            f"{b.get('displacement_cc')}) AND power "
            f"({a.get('power_min_hp')}–{a.get('power_max_hp')} vs "
            f"{b.get('power_min_hp')}–{b.get('power_max_hp')})."
        )
    return errors


def _mergeable(a: dict, b: dict) -> bool:
    """Are these the same powertrain described twice?

    Stricter than `indistinguishable`: merging is only safe when the rows agree
    on the *engineering* identity too (engine family, gearbox code, gearbox
    type). Two rows that share cc+power but name different gearboxes are a
    catalog error to report, not rows to fuse.
    """
    keys = ("make", "model", "fuel", "engine_family", "transmission",
            "transmission_code", "generation")
    if any(a.get(k) != b.get(k) for k in keys):
        return False
    if not _cc_overlaps(a, b, tol=0):
        return False
    return _power_overlaps(a, b)


def _merge(a: dict, b: dict) -> dict:
    """Fuse two descriptions of one powertrain: widest window, widest power."""
    out = dict(a)
    out["power_min_hp"] = min((v for v in (a.get("power_min_hp"),
                                           b.get("power_min_hp")) if v is not None),
                              default=None)
    out["power_max_hp"] = max((v for v in (a.get("power_max_hp"),
                                           b.get("power_max_hp")) if v is not None),
                              default=None)
    out["year_from"] = min(a["year_from"], b["year_from"])
    if a.get("year_to") is None or b.get("year_to") is None:
        out["year_to"] = None
    else:
        out["year_to"] = max(a["year_to"], b["year_to"])
    if a.get("draft") or b.get("draft"):
        out["draft"] = True
    return out


def collapse_duplicates(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Merge rows that describe the same powertrain. Returns (rows, notes).

    This is what turns a trim-shaped lineup into a catalog: four Golf 8 rows
    (Impression / Life / Style / R-Line) are two powertrains, and the trim
    name is not something a listing reliably carries — so it cannot be an
    identity axis. Merging is deterministic and reported, never silent: each
    note names the rows that were fused so the agent's report says so too.
    """
    out: list[dict] = []
    notes: list[str] = []
    for row in rows:
        for i, kept in enumerate(out):
            if _mergeable(kept, row):
                out[i] = _merge(kept, row)
                notes.append(
                    f"merged {row.get('id')!r} into {kept.get('id')!r} — same "
                    f"powertrain ({row.get('engine_family')}, "
                    f"{row.get('transmission_code')}, "
                    f"{row.get('displacement_cc')}cc): a listing cannot tell "
                    f"trim levels apart")
                break
        else:
            out.append(dict(row))
    return out, notes


def model_slug(model_key: str) -> str:
    """`volkswagen_golf_8` -> `golf8` — the prefix catalog ids already use."""
    _, _, rest = model_key.partition("_")
    return re.sub(r"[^a-z0-9]", "", rest.lower()) or model_key


def canonical_variant_id(model_key: str, row: dict) -> str:
    """Derive a variant id from the powertrain it describes.

    `{model}{gen}_{engine_family}_{power}[_{gearbox}]` — e.g.
    `golf8_ea211evo2_150_dq381`. The gearbox suffix is only added for
    automatics, matching the existing convention (`golf7_ea211_125_dsg`), and
    it carries the *unit code*, so two automatics on different boxes never
    collide. Deriving the id is what stops a trim name from becoming identity.
    """
    family = re.sub(r"[^a-z0-9]", "", canonical_code(row.get("engine_family")))
    power = row.get("power_max_hp") or row.get("power_min_hp")
    bits = [model_slug(model_key), family or "unknown"]
    if power:
        bits.append(str(int(power)))
    if row.get("transmission") == "automatic":
        tx = canonical_code(row.get("transmission_code"))
        # An unresearched gearbox ("7-speed DSG") must not be baked into an id
        # — the id would then assert a unit that does not exist. `_auto` keeps
        # the row distinct from its manual sibling until the code is sourced.
        usable = tx and tx != MANUAL_CODE and not code_errors(
            "transmission_code", tx, "automatic")
        bits.append(re.sub(r"[^a-z0-9]", "", tx) if usable else "auto")
    return "_".join(bits)
