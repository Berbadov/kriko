"""search_templates.py — generate part-centric search queries for auto discovery.

Part-centric research targets the engineering code directly ("K9K 1.5 dCi timing belt
problems") rather than the car model ("Renault Megane reliability"). This produces
cross-model results — sources about the K9K in a Clio 4 are equally relevant to
the same engine in a Megane 4.

Usage (called by auto.py with --part flag):
    from packs.cars.pipeline.parts.search_templates import templates_for_part
    queries = templates_for_part("k9k", "engine", {"fuel": "diesel"})
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from packs.cars.pipeline.paths import REPO_ROOT
PARTS_DIR = REPO_ROOT / "packs" / "cars" / "data" / "parts"

# Part IDs follow a power-split convention (k9k_85, h5h_130, ea888_230, ...) —
# each power tune is researched as its own part (see write_variants.py). The
# trailing "_<hp>" is an internal bookkeeping suffix, not part of the real
# engine code: nobody writes "K9K_85 turbo arıza" on a forum, they write "K9K".
# Search text must use the bare code; file lookups (_part_meta, fitment
# matching) must keep using the exact part_id, since that's the file key.
_POWER_SUFFIX_RE = re.compile(r"_\d+$")


def _search_code(part_id: str) -> str:
    """Real-world engine/transmission code for search text (strips a trailing
    power suffix): "k9k_85" -> "K9K", "h5h_130" -> "H5H", "dq200" -> "DQ200".
    """
    return _POWER_SUFFIX_RE.sub("", part_id).upper()


def _part_meta(part_id: str) -> dict:
    """Load part YAML metadata (display_name, known_also_as, etc.)."""
    for path in PARTS_DIR.rglob(f"{part_id}.yaml"):
        data = yaml.safe_load(path.read_text()) or {}
        if data.get("part_id") == part_id:
            return data
    return {}


def generate_part_scaffold(
    part_id: str, part_type: str, make: str, model: str, variants: list[dict],
) -> dict:
    """Build the part_id/part_type/display_name/manufacturer/known_also_as
    scaffold for a new part YAML. Shared by auto._ensure_part_stub (create
    path) and catalog.repair_missing_stub_scaffold (repair path) so the two
    can't drift — see docs/pipeline_postmortem.md and design_flaws.md Flaw 2
    for the bug this caused when run_part() forgot to call it.
    """
    make_pretty = make.replace("_", " ").title()
    model_pretty = model.replace("_", " ").title()

    if part_type == "engine":
        codes: list[str] = []
        descs: list[str] = []
        for v in variants:
            if (v.get("engine_family") or "").lower() == part_id.lower():
                ec = (v.get("engine_code") or "").upper()
                if ec and ec not in codes:
                    codes.append(ec)
                fuel = (v.get("fuel") or "").lower()
                cc = v.get("displacement_cc")
                if cc:
                    litre = f"{cc / 1000:.1f}"
                    fuel_tag = "TSI" if fuel == "petrol" else "TDI" if fuel == "diesel" else fuel.upper()
                    label = f"{litre} {fuel_tag}"
                    if label not in descs:
                        descs.append(label)
        display_name = f"{make_pretty} {_search_code(part_id)} Engine"
        known_also_as = codes + descs

    elif part_type == "transmission":
        display_name = f"{make_pretty} {_search_code(part_id)} Transmission"
        known_also_as = [_search_code(part_id)]

    elif part_type == "cooling":
        display_name = f"{make_pretty} {model_pretty} Cooling System"
        known_also_as = [
            f"{make_pretty} {model_pretty} cooling",
            f"{make_pretty} {model_pretty} coolant",
            f"{make_pretty} {model_pretty} thermostat",
        ]

    elif part_type == "electrical":
        display_name = f"{make_pretty} {model_pretty} Electrical Systems"
        known_also_as = [
            f"{make_pretty} {model_pretty} electrical",
            f"{make_pretty} {model_pretty} electronics",
            f"{make_pretty} {model_pretty} battery",
        ]

    elif part_type == "body":
        display_name = f"{make_pretty} {model_pretty} Body & Water Sealing"
        known_also_as = [
            f"{make_pretty} {model_pretty} body",
            f"{make_pretty} {model_pretty} boot leak",
            f"{make_pretty} {model_pretty} water ingress",
        ]

    else:
        display_name = f"{make_pretty} {model_pretty} {_search_code(part_id)}"
        known_also_as = [_search_code(part_id)]

    scaffold = {
        "part_id": part_id,
        "part_type": part_type,
        "display_name": display_name,
        "manufacturer": make,
        "known_also_as": known_also_as,
    }
    if part_type in ("engine", "transmission"):
        # Default a new part to its own singleton family (no known siblings
        # yet) — the field is always present so validate_part_yaml.py's hard
        # check passes immediately, with no separate registration step. If a
        # human later discovers this code is a sibling of an existing family
        # (e.g. a new DSG generation joining vw_dsg_dct), they just edit this
        # one line on this one file — see packs/cars/pipeline/stoplists.py's
        # catalog_sibling_families() for how this field is consumed.
        scaffold["code_family"] = _search_code(part_id).lower()
    return scaffold


def ensure_part_stub(
    part_id: str,
    part_type: str,
    make: str,
    model: str,
    variants: list[dict],
    *,
    dry_run: bool = False,
) -> None:
    """Create a minimal part stub YAML if one doesn't exist yet.

    Shared by every part-writing entry point — write_promoted_part_claims
    only *preserves*
    existing scaffold metadata, it never creates it, so any pipeline path
    that skips this on a genuinely new part_id writes a file containing only
    {"claims": [...]}, missing part_id/part_type/display_name/manufacturer
    entirely (see docs/design_flaws.md Flaw 2 postmortem note: this bug hit
    twice, once in auto.py's --part path and once in process.py's, because
    the two entry points didn't share this call).
    """
    stub_path = PARTS_DIR / part_type / f"{part_id}.yaml"
    if stub_path.exists():
        return
    if dry_run:
        print(f"  [dry-run] Would create part stub: {stub_path.relative_to(REPO_ROOT)}")
        return

    scaffold = generate_part_scaffold(part_id, part_type, make, model, variants)

    stub_path.parent.mkdir(parents=True, exist_ok=True)
    stub_path.write_text(
        yaml.dump({**scaffold, "claims": []}, allow_unicode=True, sort_keys=False)
    )
    print(f"  Created part stub: {stub_path.relative_to(REPO_ROOT)}")


def _find_make_model_for_part(part_id: str, part_type: str) -> tuple[str, str]:
    """Find make and model associated with a part ID by scanning the fitment catalog.

    Fitment filenames are "{make}_{model}.yaml" where model itself may contain
    underscores (a generation suffix: "golf_7", "megane_4", "clio_5") — the
    model is everything after the first underscore, not just stem_parts[1].
    Truncating to stem_parts[1] (e.g. "golf" instead of "golf_7") silently
    breaks every caller that reassembles f"{make}_{model}.yaml" to find the
    variants file, since that file doesn't exist under the truncated name —
    this is why the ensure_part_stub call in both auto.py and process.py's
    run_part() looked correct but never actually fired for any real model.
    """
    fitment_dir = PARTS_DIR.parent / "fitment"
    field = {
        "engine": "engine_family",
        "transmission": "transmission_code",
        "cooling": "cooling_code",
        "electrical": "electrical_code",
        "body": "body_code",
    }.get(part_type, "engine_family")

    for path in fitment_dir.glob("*.yaml"):
        stem_parts = path.stem.split("_")
        if len(stem_parts) >= 2:
            make = stem_parts[0]
            model = "_".join(stem_parts[1:])
            try:
                rows = yaml.safe_load(path.read_text()) or []
                for row in rows:
                    if row.get(field) == part_id:
                        return make, model
            except Exception:
                continue
    return "", ""


def templates_for_part(
    part_id: str,
    part_type: str,
    hints: dict | None = None,
) -> list[tuple[str, str]]:
    """Return (domain, query) pairs for searching sources about this part revision.

    hints: optional dict with keys like fuel ("diesel"|"petrol"), displacement ("1.5"),
    manufacturer, etc. — used to make queries more specific.
    """
    code = _search_code(part_id)
    meta = _part_meta(part_id)
    display = meta.get("display_name", code)
    aliases = meta.get("known_also_as", [])
    fuel = (hints or {}).get("fuel", "")

    make, model = _find_make_model_for_part(part_id, part_type)
    make_t = make.title() if make else ""
    model_t = model.replace("_", " ").title() if model else ""

    templates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(domain: str, query: str) -> None:
        if query not in seen:
            seen.add(query)
            templates.append((domain, query))

    # ── Primary code queries ──────────────────────────────────────────────────
    if make_t and model_t:
        if part_type == "engine":
            add("engine", f"{make_t} {model_t} {code} chronic and common problems")
        elif part_type == "transmission":
            add("transmission", f"{make_t} {model_t} {code} chronic and common problems")
        elif part_type == "cooling":
            add("cooling", f"{make_t} {model_t} Cooling chronic problems")
        elif part_type == "electrical":
            add("electrical", f"{make_t} {model_t} electronics chronic problems")
        elif part_type == "body":
            add("body", f"{make_t} {model_t} water leak chronic problems")

    add(part_type, f"{code} {part_type} problems reliability")
    add(part_type, f"{code} motor arıza sorun")
    add(part_type, f"{display} common problems")
    add(part_type, f"{display} known issues reliability")

    # ── Alias queries ──────────────────────────────────────────────────────────
    for alias in aliases[:3]:  # cap aliases to avoid explosion
        add(part_type, f"{alias} reliability issues")
        add(part_type, f"{alias} arıza sorun")

    # ── Fuel-type specific (Engine only) ───────────────────────────────────────
    if part_type == "engine":
        if fuel == "diesel":
            add("engine",    f"{code} timing belt replacement interval")
            add("engine",    f"{code} EGR valve clogging failure")
            add("engine",    f"{code} enjektör arıza")
            add("engine",    f"{code} turbo actuator failure")
            add("engine",    f"{code} turbo arıza")
            add("emissions", f"{code} DPF regeneration failure")
            add("emissions", f"{code} DPF sorun")
        elif fuel == "petrol":
            add("engine", f"{code} timing chain tensioner failure")
            add("engine", f"{code} oil consumption turbo")
            add("engine", f"{code} zincirleme arıza")

        # Engine cooling/thermostat (fuel-agnostic)
        add("engine", f"{code} thermostat housing cracking failure")
        add("engine", f"{code} water pump coolant leak")
        add("engine", f"{code} termostat arıza")

    # ── Transmission-specific ─────────────────────────────────────────────────
    if part_type == "transmission":
        add("transmission", f"{code} gearbox problems reliability")
        add("transmission", f"{display} mechatronics failure")
        add("transmission", f"{display} şanzıman arıza")
        add("transmission", f"{display} clutch shudder judder problem")
        add("transmission", f"{display} TCU software update fault")
        add("transmission", f"{code} transmission sorun")

    # ── Body / water-sealing specific ──────────────────────────────────────────
    # part_id (e.g. "golf7_body") is an internal fitment key, not a real-world
    # search term, so these lean on make/model rather than part_id.upper().
    if part_type == "body" and make_t and model_t:
        add("body", f"{make_t} {model_t} boot trunk water leak")
        add("body", f"{make_t} {model_t} bagaj su alma sızıntı")
        add("body", f"{make_t} {model_t} sunroof drain blocked flooding")
        add("body", f"{make_t} {model_t} sunroof drenaj tıkanması")
        add("body", f"{make_t} {model_t} tailgate wiring loom corrosion rear camera fault")
        add("body", f"{make_t} {model_t} arka cam sileceği kablo demeti arıza")
        add("body", f"{make_t} {model_t} rear light cluster seal leak condensation")
        add("body", f"{make_t} {model_t} stop lambası sızdırma buğulanma")
        add("body", f"{make_t} {model_t} windscreen cowl scuttle drain clogged")
        add("body", f"{make_t} {model_t} footwell wet carpet damp mould")
        add("body", f"{make_t} {model_t} ayak altı nem küf halı ıslanma")
        add("body", f"{make_t} {model_t} door seal water ingress wind noise")
        add("body", f"{make_t} {model_t} wheel arch liner corrosion drainage")

    return templates
