"""write_variants.py — procedurally generate a new model's TR-market variants YAML.

catalog.discover finds engine/transmission *codes* from Wikipedia, but the TR-market
lineup — which trims were actually sold in Turkey, at what power/year, on what
gearbox — isn't in a machine-readable source; it's domain knowledge. Per CLAUDE.md,
`backend/data/*` is never hand-written, so that domain knowledge lives here as data
in a script (reviewable, diffable, rerunnable) instead of typed directly into YAML.

Each model's trim list is cross-checked against catalog.discover's Wikipedia-derived
engine families/fuels and logs a warning on mismatch, but hand-curated data wins —
Wikipedia infoboxes are noisy (e.g. list engines from special editions never sold
in TR, or omit automatic-transmission variants entirely).

Usage:
    python -m knowledge.catalog.write_variants --make renault --model clio_5
    python -m knowledge.catalog.write_variants --make volkswagen --model golf_7 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import yaml

from knowledge.catalog import identity
from knowledge.catalog.discover import discover

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
VARIANTS_DIR = REPO_ROOT / "backend" / "data" / "variants"
FITMENT_DIR = REPO_ROOT / "backend" / "data" / "fitment"

# TR-market trim data, keyed by "{make}_{model}". Each row matches the schema
# already used by hand-curated files (renault_megane_4.yaml, volkswagen_golf_7.yaml):
# id, make, model, generation, engine_code, engine_family, fuel, displacement_cc,
# power_min_hp, power_max_hp, transmission, transmission_code, electrical_code,
# body_code, year_from, year_to, market, notes, drivetrain.
#
# engine_family follows the current power-split convention (e.g. "h5h_130", not
# bare "h5h") — each power tune is researched as its own part, consistent with
# volkswagen_golf_7.yaml (ea211/ea288/ea888 are exceptions, kept as engine-family-
# wide research keys rather than split further — see docs/design_flaws.md Flaw 2:
# power tune doesn't change engineering identity, so splitting on it just pays
# for duplicate research of the same physical engine).
TR_MARKET_TRIMS: dict[str, list[dict]] = {
    "renault_clio_5": [
        {
            "id": "clio5_h4d_75", "generation": "V", "engine_code": "H4D", "engine_family": "h4d_75",
            "fuel": "petrol", "displacement_cc": 999, "power_min_hp": 75, "power_max_hp": 75,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2019, "year_to": 2023, "notes": "SCe 75 — naturally aspirated 3-cyl, base trim, manual only",
        },
        {
            "id": "clio5_h5d_100", "generation": "V", "engine_code": "H5Dt", "engine_family": "h5d_100",
            "fuel": "petrol", "displacement_cc": 999, "power_min_hp": 90, "power_max_hp": 100,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2019, "year_to": None, "notes": "TCe 90/100 — turbocharged 3-cyl, volume trim, manual",
        },
        {
            "id": "clio5_h5d_100_edc", "generation": "V", "engine_code": "H5Dt", "engine_family": "h5d_100",
            "fuel": "petrol", "displacement_cc": 999, "power_min_hp": 100, "power_max_hp": 100,
            "transmission": "automatic", "transmission_code": "dc4",
            "year_from": 2019, "year_to": None, "notes": "TCe 100 EDC — same engine as manual, 7-speed dual-clutch (DC4 unit — same part as Megane 4's H5F EDC, already researched)",
        },
        {
            "id": "clio5_h5h_130", "generation": "V", "engine_code": "H5Ht", "engine_family": "h5h_130",
            "fuel": "petrol", "displacement_cc": 1332, "power_min_hp": 130, "power_max_hp": 130,
            "transmission": "automatic", "transmission_code": "dc4",
            "year_from": 2019, "year_to": 2022, "notes": "TCe 130 — EDC only, GT-Line trim; same engine family as Megane 4 H5H but a distinct power tune/part. Transmission (DC4) is shared with Megane 4's EDC, already researched.",
        },
        {
            "id": "clio5_k9k_85", "generation": "V", "engine_code": "K9K", "engine_family": "k9k_85",
            "fuel": "diesel", "displacement_cc": 1461, "power_min_hp": 75, "power_max_hp": 85,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2019, "year_to": 2021, "notes": "Blue dCi 85 — entry diesel, dropped from range as EU7 prep reduced small-diesel offers",
        },
        {
            "id": "clio5_k9k_100", "generation": "V", "engine_code": "K9K", "engine_family": "k9k_100",
            "fuel": "diesel", "displacement_cc": 1461, "power_min_hp": 95, "power_max_hp": 100,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2019, "year_to": None, "notes": "Blue dCi 100 — volume diesel trim",
        },
    ],
    "volkswagen_golf_7": [
        # EA211 petrol. The 1.0/1.2/1.4 TSI are the SAME engine family (EA211),
        # so they share one research key and inherit each other's part claims —
        # only displacement/power/gearbox separate them as variants.
        {
            "id": "golf7_ea211_105", "generation": "VII", "engine_code": "EA211", "engine_family": "ea211",
            "fuel": "petrol", "displacement_cc": 998, "power_min_hp": 105, "power_max_hp": 105,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2017, "year_to": 2020, "notes": "1.0 TSI — 3-cyl, facelift base petrol, replaced the 1.2 TSI",
        },
        {
            "id": "golf7_ea211_110", "generation": "VII", "engine_code": "EA211", "engine_family": "ea211",
            "fuel": "petrol", "displacement_cc": 1197, "power_min_hp": 105, "power_max_hp": 110,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2013, "year_to": 2017, "notes": "1.2 TSI (BMT) — 105 hp CJZA, 110 hp CYVB from 2015; volume petrol until the facelift's 1.0 TSI replaced it",
        },
        {
            "id": "golf7_ea211_110_dsg", "generation": "VII", "engine_code": "EA211", "engine_family": "ea211",
            "fuel": "petrol", "displacement_cc": 1197, "power_min_hp": 105, "power_max_hp": 110,
            "transmission": "automatic", "transmission_code": "dq200",
            "year_from": 2013, "year_to": 2017, "notes": "1.2 TSI DSG — 7-speed dry-clutch DQ200, same unit as the 1.4 TSI DSG (already researched)",
        },
        {
            "id": "golf7_ea211_125", "generation": "VII", "engine_code": "EA211", "engine_family": "ea211",
            "fuel": "petrol", "displacement_cc": 1395, "power_min_hp": 125, "power_max_hp": 125,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2013, "year_to": 2020, "notes": "1.4 TSI — volume petrol, 6MT",
        },
        {
            "id": "golf7_ea211_125_dsg", "generation": "VII", "engine_code": "EA211", "engine_family": "ea211",
            "fuel": "petrol", "displacement_cc": 1395, "power_min_hp": 125, "power_max_hp": 125,
            "transmission": "automatic", "transmission_code": "dq200",
            "year_from": 2013, "year_to": 2020, "notes": "1.4 TSI DSG — 7-speed dry-clutch DQ200",
        },
        # EA288 diesel.
        {
            "id": "golf7_ea288_105", "generation": "VII", "engine_code": "EA288", "engine_family": "ea288",
            "fuel": "diesel", "displacement_cc": 1598, "power_min_hp": 105, "power_max_hp": 105,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2013, "year_to": 2020, "notes": "1.6 TDI — entry diesel, 5/6MT",
        },
        {
            "id": "golf7_ea288_150", "generation": "VII", "engine_code": "EA288", "engine_family": "ea288",
            "fuel": "diesel", "displacement_cc": 1968, "power_min_hp": 150, "power_max_hp": 150,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2013, "year_to": 2020, "notes": "2.0 TDI — volume diesel, 6MT",
        },
        {
            "id": "golf7_ea288_150_dsg", "generation": "VII", "engine_code": "EA288", "engine_family": "ea288",
            "fuel": "diesel", "displacement_cc": 1968, "power_min_hp": 150, "power_max_hp": 150,
            "transmission": "automatic", "transmission_code": "dq250",
            "year_from": 2013, "year_to": 2020, "notes": "2.0 TDI DSG — 6-speed wet-clutch DQ250",
        },
        # EA888 petrol (GTI / R).
        {
            "id": "golf7_ea888_220", "generation": "VII", "engine_code": "EA888", "engine_family": "ea888",
            "fuel": "petrol", "displacement_cc": 1984, "power_min_hp": 220, "power_max_hp": 220,
            "transmission": "automatic", "transmission_code": "dq250",
            "year_from": 2013, "year_to": 2016, "notes": "GTI (pre-facelift) — 2.0 TSI EA888 Gen3, 6-speed wet DSG or 6MT",
        },
        {
            "id": "golf7_ea888_230", "generation": "VII", "engine_code": "EA888", "engine_family": "ea888",
            "fuel": "petrol", "displacement_cc": 1984, "power_min_hp": 230, "power_max_hp": 245,
            "transmission": "automatic", "transmission_code": "dq381",
            "year_from": 2017, "year_to": 2020, "notes": "GTI/GTI Performance (facelift) — 2.0 TSI EA888 Gen3, 7-speed wet DSG or 6MT",
        },
        {
            "id": "golf7_ea888_300", "generation": "VII", "engine_code": "EA888", "engine_family": "ea888",
            "fuel": "petrol", "displacement_cc": 1984, "power_min_hp": 300, "power_max_hp": 310,
            "transmission": "automatic", "transmission_code": "dq381",
            "year_from": 2014, "year_to": 2020, "notes": "R — 2.0 TSI EA888 Gen3, Haldex AWD, DQ250 pre-facelift/DQ381 facelift (simplified to dq381 here)",
            "drivetrain": "awd",
        },
    ],
}

# electrical_code / body_code per model — one shared fitment axis per generation,
# not per engine (matches golf7_elec/golf7_body convention).
_SHARED_CODES: dict[str, dict[str, str]] = {
    "renault_clio_5": {"electrical_code": "clio5_elec", "body_code": "clio5_body"},
    "volkswagen_golf_7": {"electrical_code": "golf7_elec", "body_code": "golf7_body"},
}


# ── Trim validation (B23: agent-supplied trims) ──────────────────────────────
#
# Closed engineering vocabularies, not car-coverage data — allowed as constants
# under CLAUDE.md's scalability-rule exception. They do not grow when a new
# model is onboarded; only TR_MARKET_TRIMS did, which is exactly why an agent
# now supplies those rows instead of a human editing this file.
_VALID_FUELS = {"petrol", "diesel", "hybrid", "lpg", "electric"}
_VALID_TRANSMISSIONS = {"manual", "automatic"}
_VALID_EMISSIONS = {"euro4", "euro5", "euro6b", "euro6c", "euro6d", "euro6d_temp"}

# Identity: without these a row cannot be resolved to a part or matched to a
# listing, so a missing one is a hard error rather than a fail-open gap.
_REQUIRED_TRIM_KEYS = ("id", "engine_code", "engine_family", "fuel",
                       "transmission", "transmission_code", "year_from")

# Figures that fail open. The agent omits what it cannot source; the row is
# written `draft: true`, backend/sync.py skips it, and the coverage report
# raises `draft_variant`. Never guessed (CLAUDE.md automation principle).
_SOURCED_FIGURES = ("displacement_cc", "power_min_hp", "power_max_hp")


def normalize_trims(trims: list[dict]) -> list[dict]:
    """Put agent-supplied rows into catalog form before anything validates them.

    Researchers type codes the way the source printed them ("EA211_evo2",
    "7-speed DSG", "6MT"); the catalog stores them as lowercase `_`-separated
    codes, and files manual boxes under the `manual` pseudo-code because a
    manual gearbox has no part file. Normalizing first means the validator
    reports *real* problems ("DSG names three gearboxes") instead of casing.
    """
    out = []
    for t in trims:
        row = dict(t)
        for field in ("engine_family", "transmission_code",
                      "electrical_code", "body_code"):
            if row.get(field) is not None:
                row[field] = identity.canonical_code(row[field])
        if row.get("transmission") == "manual" and \
                identity.is_manualish(row.get("transmission_code") or ""):
            row["transmission_code"] = identity.MANUAL_CODE
        if row.get("fuel"):
            row["fuel"] = str(row["fuel"]).strip().lower()
        if row.get("transmission"):
            row["transmission"] = str(row["transmission"]).strip().lower()
        out.append(row)
    return out


def _id_errors(where: str, trim: dict, model_key: str) -> list[str]:
    """Is this id naming the powertrain, or the showroom?

    Catalog ids carry the engine code (`clio5_h4d_75`, `golf7_ea211_125_dsg`)
    because the row *is* a powertrain: one row covers every trim level sold
    with that engine and gearbox. An id like `impression_1_5_tsi_150_manual`
    silently asserts the opposite — that trim is an identity axis — and a
    listing almost never states its trim, so the row can never be matched as
    intended. Deterministic check: the id must contain the engine family's
    code token.
    """
    tid = str(trim.get("id") or "")
    family = identity.canonical_code(trim.get("engine_family"))
    token = re.split(r"[_\d]", family, maxsplit=1)[0] if family else ""
    if not tid or not token or token in tid.lower().replace("-", "_"):
        return []
    suggestion = identity.canonical_variant_id(model_key or "x_y", trim)
    return [f"{where}: variant id does not name the powertrain (engine family "
            f"{family!r}) — a row covers every trim sold with this engine, and "
            f"a listing does not state its trim. Use something like "
            f"{suggestion!r}"]


def validate_trims(trims: list[dict], make: str = "", model: str = "") -> list[str]:
    """Deterministic structural check on agent-supplied trim rows.

    Returns a list of human-readable errors; empty means the rows are safe to
    build. Only catches what a rule can decide — whether a K9K really made
    110hp in Turkey is not knowable here, so an unsourced figure is a draft
    row, not an error.

    Two classes of error are hard rejections because they poison identity
    downstream (see `knowledge/catalog/identity.py`):
      * a part code that is a marketing description or a shared technology
        family rather than a unit code — it names the file claims attach to;
      * two rows a listing could never tell apart — an ambiguity the matcher
        can never resolve. `run()` collapses genuine duplicates first, so what
        survives to here is a real contradiction, not a trim-shaped lineup.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for i, t in enumerate(trims):
        where = t.get("id") or f"trim[{i}]"

        for key in _REQUIRED_TRIM_KEYS:
            if t.get(key) in (None, ""):
                errors.append(f"{where}: missing required key {key!r}")

        for field in ("engine_family", "transmission_code"):
            if t.get(field):
                errors.extend(
                    f"{where}: {e}" for e in identity.code_errors(
                        field, identity.canonical_code(t[field]),
                        t.get("transmission")))

        errors.extend(_id_errors(where, t, f"{make.lower()}_{model.lower()}"
                                 if make and model else ""))

        if (tid := t.get("id")) in seen:
            errors.append(f"{where}: duplicate trim id")
        elif tid:
            seen.add(tid)

        if (fuel := t.get("fuel")) and fuel not in _VALID_FUELS:
            errors.append(
                f"{where}: fuel {fuel!r} not one of {sorted(_VALID_FUELS)}")

        if (tx := t.get("transmission")) and tx not in _VALID_TRANSMISSIONS:
            errors.append(
                f"{where}: transmission {tx!r} not one of "
                f"{sorted(_VALID_TRANSMISSIONS)}")

        y_from, y_to = t.get("year_from"), t.get("year_to")
        if y_from is not None and y_to is not None and y_to < y_from:
            errors.append(f"{where}: year_to {y_to} precedes year_from {y_from}")

        lo, hi = t.get("power_min_hp"), t.get("power_max_hp")
        if lo is not None and hi is not None and hi < lo:
            errors.append(f"{where}: power_max_hp {hi} below power_min_hp {lo}")

        errors.extend(_emissions_errors(where, t.get("emissions")))
    return errors


def identity_errors(make: str, model: str, rows: list[dict],
                    existing: list[dict] | None = None) -> list[str]:
    """Rows a listing could not tell apart — within the lineup and against the
    catalog already on disk.

    Checked on built rows (not raw trims) because emissions year-splits and the
    fitment projection both happen there, and it is the *written* file CI reads.
    """
    return identity.find_overlaps(list(existing or []) + list(rows))


def _emissions_errors(where: str, em) -> list[str]:
    """Validate `emissions` in either shape: a plain era or year-split segments."""
    if em is None:
        return []
    if isinstance(em, str):
        return ([] if em in _VALID_EMISSIONS else
                [f"{where}: emissions {em!r} not one of {sorted(_VALID_EMISSIONS)}"])
    if not isinstance(em, list):
        return [f"{where}: emissions must be a string or a list of segments"]

    errors = []
    for seg in em:
        if not isinstance(seg, dict):
            errors.append(f"{where}: emissions segment must be a mapping")
            continue
        value = seg.get("emissions")
        if value not in _VALID_EMISSIONS:
            errors.append(
                f"{where}: segment emissions {value!r} not one of "
                f"{sorted(_VALID_EMISSIONS)}")
        if seg.get("year_from") is None:
            errors.append(f"{where}: emissions segment missing year_from")
    return errors


def _cross_check(make: str, model: str, trims: list[dict]) -> None:
    """Warn (don't block) if a trim's engine code isn't in Wikipedia's discovered list."""
    try:
        catalog = discover(make, model)
    except Exception as exc:
        log.warning("Could not fetch Wikipedia catalog for cross-check: %s", exc)
        return
    known_codes = {s.engine_code.upper() for s in catalog.engines}
    for t in trims:
        code = t["engine_code"].upper()
        if code not in known_codes and code.rstrip("T") not in known_codes:
            log.warning(
                "Trim %s: engine code %s not found in Wikipedia infobox for %s %s "
                "(hand-curated data kept — Wikipedia infoboxes are known to be incomplete)",
                t["id"], code, make, model,
            )


def _emissions_segments(trim: dict) -> list[dict]:
    """Expand a trim's emissions into one row-segment per emission era (B11).

    `emissions` may be a single string (one era — the trim stays one row) or a
    list of year-bounded segments for mid-life aftertreatment changes that a
    single row cannot express (e.g. 1.5 dCi: LNT until 2018, then SCR):

        emissions:
          - year_from: 2016
            year_to: 2018
            emissions: euro6b
          - year_from: 2018
            year_to: 2020
            emissions: euro6d_temp

    A segment emits its own variant row (id suffixed with the sanitized
    emissions value, year window narrowed to the segment), so the SCR gate can
    ground per-era instead of guessing. Segments must fall inside the trim's
    own year window — the trim is the outer bound.
    """
    em = trim.get("emissions")
    if em is None:
        return [{"year_from": trim.get("year_from"), "year_to": trim.get("year_to"),
                 "emissions": None, "aftertreatment": trim.get("aftertreatment")}]
    if isinstance(em, str):
        return [{"year_from": trim.get("year_from"), "year_to": trim.get("year_to"),
                 "emissions": em, "aftertreatment": trim.get("aftertreatment")}]
    t_from, t_to = trim.get("year_from"), trim.get("year_to")
    segments = []
    for seg in em:
        sf, st = seg.get("year_from"), seg.get("year_to")
        if sf is None or st is None:
            raise ValueError(
                f"trim {trim['id']!r}: emissions segments need year_from and year_to")
        if not seg.get("emissions"):
            raise ValueError(
                f"trim {trim['id']!r}: emissions segment {sf}-{st} has no emissions value")
        if sf < t_from or (t_to is not None and st > t_to):
            raise ValueError(
                f"trim {trim['id']!r}: emissions segment {sf}-{st} falls outside "
                f"the trim's own window {t_from}-{t_to}")
        segments.append({
            "year_from": sf, "year_to": st,
            "emissions": seg["emissions"],
            "aftertreatment": seg.get("aftertreatment"),
        })
    if not segments:
        raise ValueError(f"trim {trim['id']!r}: empty emissions segment list")
    return segments


def _segment_id(trim_id: str, emissions: str | None) -> str:
    """Suffixed variant id for a year-split segment: {id}__{sanitized emissions}.

    Deterministic and collision-free within a trim (each era has a distinct
    emissions value; the fitment projection follows automatically because
    fitment is a pure projection of the variant row).
    """
    if not emissions:
        return trim_id
    return f"{trim_id}__{re.sub(r'[^a-z0-9]', '', emissions.lower())}"


def _generation_of(trim: dict, model: str) -> str | None:
    """The trim's generation, or the one the model key already states.

    Model keys carry the generation (`golf_8`, `megane_4`), so a lineup that
    omits it is not missing data — it is repeating what the key says. Filling
    it here keeps `generation: null` out of agent-written rows without asking
    the researcher for a figure the caller already knows.
    """
    if trim.get("generation") not in (None, ""):
        return trim["generation"]
    suffix = model.lower().rsplit("_", 1)[-1]
    return suffix if suffix.isdigit() else None


def build_rows(make: str, model: str, trims: list[dict], shared: dict[str, str]) -> list[dict]:
    make_key, model_key = make.lower(), model.lower().split("_")[0]
    rows = []
    for t in trims:
        segments = _emissions_segments(t)
        split = isinstance(t.get("emissions"), list)
        for seg in segments:
            row = {
                "id": _segment_id(t["id"], seg["emissions"]) if split else t["id"],
                "make": make_key,
                "model": model_key,
                "generation": _generation_of(t, model),
                "engine_code": t["engine_code"],
                "engine_family": t["engine_family"],
                "fuel": t["fuel"],
                "displacement_cc": t.get("displacement_cc"),
                "power_min_hp": t.get("power_min_hp"),
                "power_max_hp": t.get("power_max_hp"),
                "transmission": t["transmission"],
                "transmission_code": t["transmission_code"],
                "electrical_code": shared.get("electrical_code", ""),
                "year_from": seg["year_from"],
                "year_to": seg["year_to"],
                "market": "TR",
                "notes": t.get("notes", ""),
                "body_code": shared.get("body_code", ""),
                "drivetrain": t.get("drivetrain", "fwd"),
            }
            # Fail open on figures the researcher could not source: mark the row
            # draft rather than guess. sync skips it, coverage reports it. Rows
            # that carry every figure are untouched — no `draft` key at all —
            # so the hardcoded TR_MARKET_TRIMS path emits identical YAML.
            if any(t.get(f) is None for f in _SOURCED_FIGURES):
                row["draft"] = True
            # B11: emissions/aftertreatment — see the SCR-gate spec §2. `emissions`
            # is per-trim data (grows with coverage); `aftertreatment` is derived
            # from fuel+emissions by the closed engineering rule, unless the
            # segment/trim carries an explicit override.
            if seg["emissions"]:
                row["emissions"] = seg["emissions"]
                row["aftertreatment"] = (
                    seg["aftertreatment"]
                    or _default_aftertreatment(t["fuel"], seg["emissions"])
                )
            rows.append(row)
    return rows


def _default_aftertreatment(fuel: str | None, emissions: str | None) -> str | None:
    """Derive aftertreatment from fuel + euro standard.

    Closed engineering vocabulary (allowed constant per CLAUDE.md), not per-model
    car data — mirrors backend/sync.py's same-named function so the generator
    writes the same value sync-time grounding would derive.
    """
    f = (fuel or "").lower()
    e = (emissions or "").lower()
    if f != "diesel":
        return "none" if f == "petrol" else None
    if e.startswith("euro6d"):
        return "scr"
    if e.startswith("euro6b") or e.startswith("euro6c"):
        return "lnt"
    return None


# The fitment axes — the part codes a variant is assembled from. Every one is
# already a column on the variant row, so fitment is a pure PROJECTION of the
# variants file, never independent data.
_FITMENT_AXES = ("engine_family", "transmission_code", "electrical_code", "body_code")


def build_fitment_rows(variant_rows: list[dict]) -> list[dict]:
    """Project variant rows into fitment rows (variant_id -> its part codes).

    sync_parts assembles claims through fitment, so a variant absent from the
    fitment file matches a listing and then serves ZERO claims — which is exactly
    what happened to the Golf 1.2 TSI when fitment was hand-maintained and got
    left behind. Deriving it removes the manual step (CLAUDE.md scalability rule).
    """
    return [
        {"variant_id": row["id"],
         **{axis: row[axis] for axis in _FITMENT_AXES if axis in row}}
        for row in variant_rows
    ]


def _write_fitment(key: str, variant_rows: list[dict], dry_run: bool,
                   fitment_dir: Path | None = None) -> None:
    """Add fitment rows for any variant that doesn't have one yet (additive)."""
    path = (fitment_dir or FITMENT_DIR) / f"{key}.yaml"
    existing: list[dict] = []
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or []
    have = {r["variant_id"] for r in existing}

    to_add = [r for r in build_fitment_rows(variant_rows) if r["variant_id"] not in have]
    if not to_add:
        return

    print(f"{'Would add' if dry_run else 'Adding'} {len(to_add)} fitment row(s) to "
          f"{_display(path)}:")
    for r in to_add:
        print(f"  {r['variant_id']}: engine={r.get('engine_family')} "
              f"tx={r.get('transmission_code')}")
    if dry_run:
        return

    path.write_text(yaml.dump(existing + to_add, allow_unicode=True, sort_keys=False))
    print(f"Wrote {_display(path)}")


def _display(path: Path) -> str:
    """Repo-relative path when it is under the repo, absolute otherwise."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def run(make: str, model: str, trims: list[dict] | None = None,
        dry_run: bool = False, variants_dir: Path | None = None,
        fitment_dir: Path | None = None) -> dict:
    """Write the variants + fitment YAML for a model.

    `trims` is the TR-market trim lineup. When omitted it falls back to the
    hardcoded TR_MARKET_TRIMS table (the CLI path, unchanged). A researcher
    agent supplies it instead via the MCP `submit_trims` tool, which is how a
    model gets onboarded without anyone hand-editing this file.

    Returns a summary so callers can report what landed and what stayed draft.
    """
    key = f"{make.lower()}_{model.lower()}"
    if trims is None:
        trims = TR_MARKET_TRIMS.get(key)
    if not trims:
        raise SystemExit(
            f"No TR-market trim data for {key!r}. Either pass trims= (the agent "
            f"path — see ops/mcp/server.py submit_trims) or add an entry "
            f"to TR_MARKET_TRIMS in {__file__}."
        )

    _cross_check(make, model, trims)
    shared = _SHARED_CODES.get(key, {})
    new_rows = build_rows(make, model, trims, shared)

    # Same powertrain described twice (a trim-shaped lineup) is fused before
    # anything is written — an ambiguity the matcher could never resolve must
    # not be creatable, not merely detectable. Reported, never silent.
    new_rows, merge_notes = identity.collapse_duplicates(new_rows)

    path = (variants_dir or VARIANTS_DIR) / f"{key}.yaml"
    existing: list[dict] = []
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or []

    existing_ids = {r["id"] for r in existing}
    to_add = [r for r in new_rows if r["id"] not in existing_ids]
    skipped = [r["id"] for r in new_rows if r["id"] in existing_ids]
    summary = {"rows_written": len(to_add), "rows_skipped": len(skipped),
               "rows_draft": sum(1 for r in new_rows if r.get("draft")),
               "merged": merge_notes,
               "path": _display(path)}

    # What survives the merge and still collides is a real contradiction (two
    # different gearboxes claiming the same cc+power+years), not a duplicate.
    # Refuse rather than write a catalog CI would reject.
    conflicts = identity_errors(make, model, to_add, existing)
    if conflicts:
        summary["errors"] = conflicts
        summary["rows_written"] = 0
        for line in conflicts:
            log.error("%s", line)
        return summary

    # Fitment is a projection of the variants, and is emitted even when no new
    # variant rows are added — a variant already in the catalog can still be
    # MISSING its fitment row (it then matches a listing and serves no claims).
    _write_fitment(key, new_rows, dry_run, fitment_dir)

    if not to_add:
        print(f"No new rows — all {len(new_rows)} variant(s) already present in {path}")
        return summary

    if skipped:
        print(f"Skipping {len(skipped)} already-present id(s): {', '.join(skipped)}")

    print(f"{'Would add' if dry_run else 'Adding'} {len(to_add)} variant(s) to {_display(path)}:")
    for r in to_add:
        print(f"  {r['id']}: {r['engine_code']} {r['fuel']} {r['displacement_cc']}cc "
              f"{r['power_min_hp']}-{r['power_max_hp']}hp {r['transmission']} ({r['transmission_code']})")

    if dry_run:
        return summary

    combined = existing + to_add
    header = ""
    if path.exists():
        text = path.read_text()
        if text.startswith("#"):
            header = "\n".join(
                line for line in text.splitlines() if line.startswith("#")
            ) + "\n\n"
    else:
        header = (
            f"# {make.title()} {model.replace('_', ' ').title()} — Turkish market variant catalog\n"
            f"# Generated by knowledge.catalog.write_variants — see TR_MARKET_TRIMS for source data.\n"
            f"# ID format: {{model}}_{{engine_code}}_{{power_hp}}[_{{tx_suffix}}]\n\n"
        )
    path.write_text(header + yaml.dump(combined, allow_unicode=True, sort_keys=False))

    print(f"Wrote {_display(path)}")
    return summary


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make", required=True)
    parser.add_argument("--model", required=True, help="Model key, e.g. clio_5, golf_7")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.make.lower(), args.model.lower(), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
