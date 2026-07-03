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

from pathlib import Path

import yaml

PARTS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "parts"


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
        "body": "body_code",
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
    meta = _part_meta(part_id)
    display = meta.get("display_name", part_id.upper())
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
            add("engine", f"{make_t} {model_t} {part_id.upper()} chronic and common problems")
        elif part_type == "transmission":
            add("transmission", f"{make_t} {model_t} {part_id.upper()} chronic and common problems")
        elif part_type == "cooling":
            add("cooling", f"{make_t} {model_t} Cooling chronic problems")
        elif part_type == "electrical":
            add("electrical", f"{make_t} {model_t} electronics chronic problems")
        elif part_type == "body":
            add("body", f"{make_t} {model_t} water leak chronic problems")

    add(part_type, f"{part_id.upper()} {part_type} problems reliability")
    add(part_type, f"{part_id.upper()} motor arıza sorun")
    add(part_type, f"{display} common problems")
    add(part_type, f"{display} known issues reliability")

    # ── Alias queries ──────────────────────────────────────────────────────────
    for alias in aliases[:3]:  # cap aliases to avoid explosion
        add(part_type, f"{alias} reliability issues")
        add(part_type, f"{alias} arıza sorun")

    # ── Fuel-type specific (Engine only) ───────────────────────────────────────
    if part_type == "engine":
        if fuel == "diesel":
            add("engine",    f"{part_id.upper()} timing belt replacement interval")
            add("engine",    f"{part_id.upper()} EGR valve clogging failure")
            add("engine",    f"{part_id.upper()} enjektör arıza")
            add("emissions", f"{part_id.upper()} DPF regeneration failure")
            add("emissions", f"{part_id.upper()} DPF sorun")
        elif fuel == "petrol":
            add("engine", f"{part_id.upper()} timing chain tensioner failure")
            add("engine", f"{part_id.upper()} oil consumption turbo")
            add("engine", f"{part_id.upper()} zincirleme arıza")

        # Engine cooling/thermostat (fuel-agnostic)
        add("engine", f"{part_id.upper()} thermostat housing cracking failure")
        add("engine", f"{part_id.upper()} water pump coolant leak")
        add("engine", f"{part_id.upper()} termostat arıza")

    # ── Transmission-specific ─────────────────────────────────────────────────
    if part_type == "transmission":
        add("transmission", f"{part_id.upper()} gearbox problems reliability")
        add("transmission", f"{display} mechatronics failure")
        add("transmission", f"{display} şanzıman arıza")
        add("transmission", f"{display} clutch shudder judder problem")
        add("transmission", f"{display} TCU software update fault")
        add("transmission", f"{part_id.upper()} transmission sorun")

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
