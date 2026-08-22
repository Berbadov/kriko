"""How the browser groups and judges catalog claims.

Extracted from web.py. Display groups come off components.yaml rather than a
list kept in sync by hand, and _gate_verdict runs the same agent write gate the
MCP server runs, so the browser and the write path cannot disagree about what
counts as low value.

_model_part_ids takes its data dir as an argument rather than reading the
module-level DATA_DIR, which is what makes it safe to live outside web.py.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from knowledge.agent import gates as agent_gates
from knowledge.catalog import model_state

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# into (engine/timing -> engine). Kept as the fallback ordering; the live set
# is derived from components.yaml so a new subsystem appears automatically.
_DISPLAY_GROUPS = ("engine", "transmission", "emissions", "brakes",
                   "suspension", "electrical", "body")
_COMPONENTS_YAML = REPO_ROOT / "knowledge" / "catalog" / "components.yaml"

# Loose claim domains fold into their parent group; 'general' has no group of
# its own and falls through to the part file's directory.
_DOMAIN_GROUPS = {
    "engine": "engine", "cooling": "engine", "fuel system": "engine",
    "transmission": "transmission", "emissions": "emissions",
    "brakes": "brakes", "suspension": "suspension",
    "electrical": "electrical", "body": "body",
}

_COMPONENTS_CACHE: dict = {}


def _component_registry() -> tuple[list[str], dict[str, str]]:
    """(display groups, component_id -> group) from components.yaml.

    The registry is the contract: a subsystem's first path segment is its
    display group, so the heatmap follows components.yaml instead of a list
    someone has to keep in sync here.
    """
    if "reg" not in _COMPONENTS_CACHE:
        groups: list[str] = []
        by_id: dict[str, str] = {}
        try:
            with open(_COMPONENTS_YAML, encoding="utf-8") as fh:
                comps = (yaml.safe_load(fh) or {}).get("components") or []
            for c in comps:
                group = str(c.get("subsystem") or "").split("/", 1)[0]
                if group and group not in groups:
                    groups.append(group)
                if c.get("id"):
                    by_id[c["id"]] = group
        except (OSError, yaml.YAMLError):
            groups = []
        ordered = [g for g in _DISPLAY_GROUPS if g in groups] + \
                  [g for g in groups if g not in _DISPLAY_GROUPS]
        _COMPONENTS_CACHE["reg"] = (ordered or list(_DISPLAY_GROUPS), by_id)
    return _COMPONENTS_CACHE["reg"]


def _claim_group(claim: dict, part_type: str) -> str | None:
    """Which display group a claim counts under, or None if unplaceable.

    component_id (components.yaml ref) wins when present; today's catalog
    YAMLs carry only `domain`, so that is the operative path.
    """
    _, by_id = _component_registry()
    cid = claim.get("component_id")
    if cid in by_id:
        return by_id[cid]
    g = _DOMAIN_GROUPS.get(str(claim.get("domain") or "").strip().lower())
    if g:
        return g
    return part_type if part_type in _DISPLAY_GROUPS else None


def _model_part_ids(model_key: str, data_dir: Path) -> set[str]:
    """Part ids one car references, via its fitment (variants as fallback)."""
    rows: list[dict] = []
    for sub in ("fitment", "variants"):
        path = data_dir / sub / f"{model_key}.yaml"
        if path.exists():
            try:
                loaded = yaml.safe_load(path.read_text()) or []
            except yaml.YAMLError:
                loaded = []
            if isinstance(loaded, list):
                rows = [r for r in loaded if isinstance(r, dict)]
            if rows:
                break
    return {p["part_id"] for p in model_state.part_work_list(rows, data_dir)}


def _gate_verdict(claim: dict) -> dict:
    """What the agent write gate would say about this claim today.

    Same function the MCP server runs before writing evidence, so the browser
    and the write path cannot disagree about what counts as low value.
    """
    src = (claim.get("sources") or [{}])[0]
    res = agent_gates.check_evidence(
        claim.get("title") or "", claim.get("rationale") or "",
        claim.get("inspection_advice") or "", claim.get("part_id"),
        src.get("url") or "")
    return {"ok": res.ok, **res.as_dict()}
