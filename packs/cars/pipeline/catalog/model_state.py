"""What state is one car in — the shared answer (B23).

Onboarding a model is a loop between an agent and a human watching it, and both
need the same answer to "what's done, what's left". The MCP `onboard_model`
tool reads this for the agent's work list; the hub's Models tab reads it for the
browser. One definition, two consumers — two copies would drift, and then the
agent and the person watching would disagree about what still needs research.

Everything here is derived from the catalog YAML on disk. Nothing is
hand-enumerated, so a new car appears the moment its variants file exists.
"""

from pathlib import Path

import yaml

from packs.cars.pipeline.paths import REPO_ROOT
DATA_DIR = REPO_ROOT / "packs" / "cars" / "data"

# The variant columns that name a part to research — the same axes the fitment
# file projects, so the work list follows the catalog instead of a list someone
# has to remember to update.
PART_AXES = ("engine_family", "transmission_code", "electrical_code", "body_code")

# Placeholder codes that are engineering vocabulary, not a researchable part.
from packs.cars.pipeline.catalog.registry import PSEUDO_PART_CODES  # noqa: F401

# Figures a researcher may fail to source. Their absence marks the row draft;
# naming them lets the UI say *which* figure is missing instead of just "draft".
SOURCED_FIGURES = ("displacement_cc", "power_min_hp", "power_max_hp")

PART_STATES = ("missing", "zero_claim", "has_claims")


def model_key(make: str, model: str) -> str:
    return f"{make.lower()}_{model.lower()}"


def _load(path: Path) -> list[dict]:
    """Parse a catalog YAML into rows; a malformed file reads as empty rather
    than taking down the caller (the hub polls this once a second)."""
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError:
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _catalog_parts(data_dir: Path) -> dict[str, dict]:
    """Every part YAML on disk, by part_id, with its servable claim count."""
    out: dict[str, dict] = {}
    for path in sorted((data_dir / "parts").rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict) or not data.get("part_id"):
            continue
        out[data["part_id"]] = {"part_type": path.parent.name,
                                "claims": len(data.get("claims") or [])}
    return out


def part_work_list(variant_rows: list[dict], data_dir: Path = DATA_DIR) -> list[dict]:
    """Every part code the variants reference, tagged with what it still needs."""
    known = _catalog_parts(data_dir)
    codes: dict[str, set[str]] = {}
    for row in variant_rows:
        for axis in PART_AXES:
            code = str(row.get(axis) or "").strip()
            if code and code not in PSEUDO_PART_CODES:
                codes.setdefault(code, set()).add(axis)

    out = []
    for code in sorted(codes):
        part = known.get(code)
        if part is None:
            state, claims, part_type = "missing", 0, ""
        elif part["claims"] == 0:
            state, claims, part_type = "zero_claim", 0, part["part_type"]
        else:
            state, claims, part_type = "has_claims", part["claims"], part["part_type"]
        out.append({"part_id": code, "part_type": part_type, "state": state,
                    "claims": claims, "axes": sorted(codes[code])})
    return out


def _drafts(variant_rows: list[dict]) -> list[dict]:
    """Draft rows and the specific figures nobody could source for them."""
    return [
        {"id": row.get("id", ""),
         "missing": [f for f in SOURCED_FIGURES if row.get(f) is None]}
        for row in variant_rows if row.get("draft")
    ]


def _rollup(parts: list[dict]) -> dict[str, int]:
    return {state: sum(1 for p in parts if p["state"] == state)
            for state in PART_STATES}


def model_state(make: str, model: str, data_dir: Path = DATA_DIR) -> dict:
    """Full onboarding state for one car: scaffold presence, draft rows with the
    figures they are missing, and the part work list."""
    key = model_key(make, model)
    v_path = data_dir / "variants" / f"{key}.yaml"
    f_path = data_dir / "fitment" / f"{key}.yaml"
    rows = _load(v_path)
    parts = part_work_list(rows, data_dir)

    return {
        "model_key": key,
        "make": make.lower(),
        "model": model.lower(),
        "has_variants": v_path.exists(),
        "has_fitment": f_path.exists(),
        "variants": len(rows),
        "variants_draft": sum(1 for r in rows if r.get("draft")),
        "drafts": _drafts(rows),
        "parts": parts,
        "rollup": _rollup(parts),
    }


def list_models(data_dir: Path = DATA_DIR) -> list[dict]:
    """Summary row for every catalogued car, for the Models list."""
    v_dir = data_dir / "variants"
    if not v_dir.exists():
        return []

    out = []
    for path in sorted(v_dir.glob("*.yaml")):
        make, _, model = path.stem.partition("_")
        if not model:
            continue
        rows = _load(path)
        if not rows:
            continue
        parts = part_work_list(rows, data_dir)
        out.append({
            "model_key": path.stem, "make": make, "model": model,
            "variants": len(rows),
            "variants_draft": sum(1 for r in rows if r.get("draft")),
            "parts": len(parts), "rollup": _rollup(parts),
        })
    return out
