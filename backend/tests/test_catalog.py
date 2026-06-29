"""Catalog linter — hard CI gate.

Within one (make, model, fuel, year), no two variants may overlap on
BOTH displacement_cc range AND power range. Overlapping would make the
matcher produce an unresolvable ambiguity that can never be narrowed to
a single variant.

This test reads all variant YAML files and fails the build if any overlap
is detected.
"""

from itertools import combinations
from pathlib import Path

import yaml
import pytest


DATA_DIR = Path(__file__).parent.parent / "data" / "variants"


def _years(v) -> range:
    return range(v["year_from"], (v["year_to"] or 2099) + 1)


def _cc_overlaps(a, b, tol: int = 100) -> bool:
    """True if the two variants' cc ranges are within matching tolerance."""
    if not a.get("displacement_cc") or not b.get("displacement_cc"):
        return True   # unknown cc → conservatively flag
    return abs(a["displacement_cc"] - b["displacement_cc"]) <= tol


def _power_overlaps(a, b, tol: int = 5) -> bool:
    """True if the two variants' power ranges overlap within matching tolerance."""
    a_min = (a.get("power_min_hp") or 0) - tol
    a_max = (a.get("power_max_hp") or 999) + tol
    b_min = (b.get("power_min_hp") or 0) - tol
    b_max = (b.get("power_max_hp") or 999) + tol
    return a_min <= b_max and b_min <= a_max


def load_all_variants() -> list[dict]:
    variants = []
    for path in sorted(DATA_DIR.glob("*.yaml")):
        rows = yaml.safe_load(path.read_text())
        variants.extend(rows)
    return variants


def find_overlaps(variants: list[dict]) -> list[str]:
    """Return human-readable descriptions of every overlapping pair."""
    errors = []
    for a, b in combinations(variants, 2):
        if a["make"] != b["make"] or a["model"] != b["model"] or a["fuel"] != b["fuel"]:
            continue
        # Check if their active year ranges overlap
        years_a = set(_years(a))
        years_b = set(_years(b))
        if not years_a & years_b:
            continue
        # They share make/model/fuel/year — now check cc + power overlap
        if _cc_overlaps(a, b) and _power_overlaps(a, b):
            errors.append(
                f"OVERLAP: {a['id']} and {b['id']} share "
                f"({a['make']}, {a['model']}, {a['fuel']}, "
                f"years {sorted(years_a & years_b)[:3]}…) "
                f"and both have overlapping cc ({a.get('displacement_cc')} vs "
                f"{b.get('displacement_cc')}) AND power "
                f"({a.get('power_min_hp')}–{a.get('power_max_hp')} vs "
                f"{b.get('power_min_hp')}–{b.get('power_max_hp')})."
            )
    return errors


def test_catalog_no_ambiguous_overlaps():
    """CI gate: no two variants within make/model/fuel/year may overlap on cc+power."""
    variants = load_all_variants()
    errors = find_overlaps(variants)
    assert not errors, "Catalog has ambiguous overlaps:\n" + "\n".join(errors)


def test_all_variants_have_required_fields():
    """Every variant must have the fields the matcher depends on."""
    required = {"id", "make", "model", "fuel", "year_from"}
    variants = load_all_variants()
    for v in variants:
        missing = required - set(v.keys())
        assert not missing, f"Variant {v.get('id', '?')} is missing fields: {missing}"


def test_variant_ids_are_unique():
    variants = load_all_variants()
    ids = [v["id"] for v in variants]
    assert len(ids) == len(set(ids)), f"Duplicate variant IDs: {[i for i in ids if ids.count(i) > 1]}"


def test_fuel_values_are_canonical():
    valid_fuels = {"petrol", "diesel", "hybrid", "electric", "lpg"}
    variants = load_all_variants()
    for v in variants:
        assert v["fuel"] in valid_fuels, (
            f"Variant {v['id']} has unrecognised fuel '{v['fuel']}'. "
            f"Valid values: {valid_fuels}"
        )
