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

    templates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(domain: str, query: str) -> None:
        if query not in seen:
            seen.add(query)
            templates.append((domain, query))

    # ── Primary code queries ──────────────────────────────────────────────────
    add("engine", f"{part_id.upper()} engine problems reliability")
    add("engine", f"{part_id.upper()} motor arıza sorun")
    add("engine", f"{display} common problems forum")
    add("engine", f"{display} known issues reliability")

    # ── Alias queries ──────────────────────────────────────────────────────────
    for alias in aliases[:3]:  # cap aliases to avoid explosion
        add("engine", f"{alias} engine reliability issues")
        add("engine", f"{alias} arıza sorun forum")

    # ── Fuel-type specific ─────────────────────────────────────────────────────
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

    # ── Transmission-specific ─────────────────────────────────────────────────
    if part_type == "transmission":
        add("transmission", f"{part_id.upper()} gearbox problems reliability")
        add("transmission", f"{display} mechatronics failure")
        add("transmission", f"{display} şanzıman arıza")
        add("transmission", f"{display} clutch shudder judder problem")
        add("transmission", f"{display} TCU software update fault")
        add("transmission", f"{part_id.upper()} transmission sorun forum")

    return templates
