"""Structured feeds (spec §2.2 stage 2): near-zero-token corroboration.

Each ingester fetches a public structured source (recall registries, MOT
statistics) and writes `documents` rows with source_type='structured' plus
pre-structured evidence rows — no extraction LLM. Structured corroboration
raises testimony-derived claims to `verified` at export (see
export.disposition), and recall evidence seeds the highest-value claim class:
config-specific, high-consequence, predictable from the listing.

Feeds are fetched per catalog model (never hand-enumerated make/model lists —
the catalog drives coverage). A feed that has no data for a model simply
ingests nothing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

VARIANTS_DIR = Path(__file__).parent.parent.parent.parent / "backend" / "data" / "variants"


def catalog_models() -> list[tuple[str, str]]:
    """(make, model) pairs straight off the variants dir — coverage grows with
    the catalog, no hand-enumerated list to go stale."""
    out = []
    for p in sorted(VARIANTS_DIR.glob("*.yaml")):
        make_model = p.stem.split("_", 1)
        if len(make_model) == 2:
            out.append((make_model[0], make_model[1]))
    return out


def model_part_hint(make: str, model_key: str, route: str) -> str:
    """Derive the model-level part hint for body/electrical routing.

    Shared by the recalls_tr and safety_gate feeds, which routed identically.
    nhtsa deliberately keeps its own variant: it derives the part id from a
    de-underscored model prefix and has no variants-file fallback, so the two
    are NOT interchangeable despite the shared name.
    """
    base = model_key.split("_")[0]
    suffix = "body" if route == "body" else "elec" if route == "elec" else ""
    if not suffix:
        return ""
    part_id = f"{base}_{suffix}"
    parts_dir = Path(__file__).parent.parent.parent.parent / "backend" / "data" / "parts"
    for sub in parts_dir.rglob(f"{part_id}.yaml"):
        return part_id
    for yaml_path in VARIANTS_DIR.glob(f"{make}_{model_key}.yaml"):
        rows = yaml.safe_load(yaml_path.read_text()) or []
        if rows:
            field = "body_code" if suffix == "body" else "electrical_code"
            hint = rows[0].get(field, "")
            if hint:
                return hint
    return ""
