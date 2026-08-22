"""Loader for knowledge/catalog/components.yaml — the component registry.

Single access point for the v3 component spine: component ids, subsystems,
detection levels, two-tier aliases, and sibling code families. The validator,
the v3 migration, sync, and the hub all read the registry through here so the
YAML file is the only source of truth.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_REGISTRY_PATH = Path(__file__).resolve().parent / "components.yaml"

DETECTIONS = frozenset({"visual", "test_drive", "diagnostic", "history_check"})

# Placeholder part codes that are engineering vocabulary, not a researchable
# part — a manual gearbox has no part file. Canonical definition: backend/sync.py,
# ops/reports/coverage.py, ops/swap.py and catalog/model_state.py all import this
# one. Closed engineering vocabulary, not car-coverage data (CLAUDE.md
# scalability exception), so it does not grow with model coverage.
PSEUDO_PART_CODES = frozenset({"manual"})


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(_REGISTRY_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "components" not in data:
        raise ValueError(f"component registry malformed: {_REGISTRY_PATH}")
    return data


def components() -> dict[str, dict]:
    """component_id -> component record (id, subsystem, display, aliases, detection)."""
    return {c["id"]: c for c in _load()["components"]}


def component_ids() -> frozenset[str]:
    return frozenset(components())


def detection_of(component_id: str) -> str | None:
    """Detection level for a component, or None when unknown."""
    comp = components().get(component_id)
    return comp["detection"] if comp else None


def subsystem_of(component_id: str) -> str | None:
    comp = components().get(component_id)
    return comp["subsystem"] if comp else None


def subsystem_groups() -> dict[str, list[str]]:
    """Display group (engine, transmission, …) -> list of subsystems under it."""
    groups: dict[str, list[str]] = {}
    for c in _load()["components"]:
        group = c["subsystem"].split("/", 1)[0]
        subs = c["subsystem"]
        if subs not in groups.setdefault(group, []):
            groups[group].append(subs)
    return groups


def attribution_safe_aliases(component_id: str) -> list[str]:
    comp = components().get(component_id)
    return list(comp["aliases"]["attribution_safe"]) if comp else []


def search_only_aliases(component_id: str) -> list[str]:
    comp = components().get(component_id)
    return list(comp["aliases"]["search_only"]) if comp else []


def all_attribution_safe_aliases() -> dict[str, list[str]]:
    """Alias string (lowercased) -> component ids it safely attributes to.

    An attribution_safe alias belongs to exactly one component by contract;
    if the registry ever violates that, the alias is dropped here rather than
    trusted (a shared alias is search_only by definition).
    """
    mapping: dict[str, set[str]] = {}
    for cid, comp in components().items():
        for alias in comp["aliases"]["attribution_safe"]:
            mapping.setdefault(alias.lower(), set()).add(cid)
    return {a: sorted(ids) for a, ids in mapping.items() if len(ids) == 1}


def code_families() -> list[dict]:
    return _load()["code_families"]


def family_of_part(part_id: str) -> dict | None:
    """The code-family record a part belongs to, or None."""
    for fam in code_families():
        if part_id in fam["parts"]:
            return fam
    return None


def siblings_of_part(part_id: str) -> list[str]:
    fam = family_of_part(part_id)
    return list(fam["siblings"]) if fam else []
