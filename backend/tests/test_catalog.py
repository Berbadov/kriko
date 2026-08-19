"""Catalog linter — hard CI gate.

Within one (make, model, fuel, year), no two variants may overlap on
displacement_cc range AND power range AND transmission. Overlapping on all
three would make the matcher produce an unresolvable ambiguity that can never
be narrowed to a single variant.

The rule itself lives in `knowledge/catalog/identity.py` and is imported here:
the agent write path (`write_variants.validate_trims`) enforces the same
function, so a lineup CI would reject is rejected at submit time instead of
hours later. Keeping a second copy here is what let the Golf 8 trim-shaped
lineup through in the first place.
"""

from pathlib import Path

import yaml

from knowledge.catalog.identity import ACCEPTED_OVERLAPS, find_overlaps  # noqa: F401

DATA_DIR = Path(__file__).parent.parent / "data" / "variants"


def load_all_variants() -> list[dict]:
    variants = []
    for path in sorted(DATA_DIR.glob("*.yaml")):
        rows = yaml.safe_load(path.read_text())
        variants.extend(rows)
    return variants


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
