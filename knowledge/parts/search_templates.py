"""search_templates.py — generate part-centric search queries for auto discovery.

Part-centric research targets the engineering code directly ("K9K 1.5 dCi timing belt
problems") rather than the car model ("Renault Megane reliability"). This produces
cross-model results — sources about the K9K in a Clio 4 are equally relevant to
the same engine in a Megane 4.

Usage (called by auto.py with --part flag):
    from knowledge.parts.search_templates import templates_for_part
    queries = templates_for_part("k9k", "engine", {"fuel": "diesel"})
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PARTS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "parts"

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


def _find_make_model_for_part(part_id: str, part_type: str) -> tuple[str, str]:
    """Find make and model associated with a part ID by scanning the fitment catalog."""
    fitment_dir = PARTS_DIR.parent / "fitment"
    field = {
        "engine": "engine_family",
        "transmission": "transmission_code",
        "cooling": "cooling_code",
        "electrical": "electrical_code",
    }.get(part_type, "engine_family")

    for path in fitment_dir.glob("*.yaml"):
        stem_parts = path.stem.split("_")
        if len(stem_parts) >= 2:
            make = stem_parts[0]
            model = stem_parts[1]
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
    model_t = model.title() if model else ""

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

    add(part_type, f"{code} {part_type} problems reliability")
    add(part_type, f"{code} motor arıza sorun")
    add(part_type, f"{display} common problems forum")
    add(part_type, f"{display} known issues reliability")

    # ── Alias queries ──────────────────────────────────────────────────────────
    for alias in aliases[:3]:  # cap aliases to avoid explosion
        add(part_type, f"{alias} reliability issues")
        add(part_type, f"{alias} arıza sorun forum")

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
        add("transmission", f"{code} transmission sorun forum")

    return templates
