"""merge_ea888_power_tunes.py — one-off migration repointing golf7's three
EA888 power-tune variants (220/230/300hp) at one engineering-identity part_id.

docs/design_flaws.md Flaw 2: ea888_220/ea888_230/ea888_300 were researched as
three separate parts even though sources can't tell them apart (same physical
Gen3 EA888) — 45 curated sources across the three files, zero URL overlap,
94 cross-file near-duplicate claim clusters. This script repoints the
existing golf7_ea888_220/230/300 variant rows at engine_family: "ea888" in
both backend/data/variants/volkswagen_golf_7.yaml and
backend/data/fitment/volkswagen_golf_7.yaml, matching the bare-code
convention already used for ea211/ea288 (see write_variants.py). It does NOT
touch power_min_hp/power_max_hp/transmission_code — those still
differentiate the three variants for matching; only the *knowledge* linkage
collapses to one shared engine identity, per the fitment-layer-not-duplicated-
research fix the doc calls for.

Run knowledge.process --part ea888 --part-type engine (after merging the
curated sources) to actually populate backend/data/parts/engine/ea888.yaml;
this script only rewires the fitment/variant linkage.

Usage:
    python -m knowledge.merge_ea888_power_tunes              # dry run — report only
    python -m knowledge.merge_ea888_power_tunes --apply       # write changes
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
VARIANTS_PATH = REPO_ROOT / "backend" / "data" / "variants" / "volkswagen_golf_7.yaml"
FITMENT_PATH = REPO_ROOT / "backend" / "data" / "fitment" / "volkswagen_golf_7.yaml"

OLD_IDS = {"ea888_220", "ea888_230", "ea888_300"}
NEW_ID = "ea888"


def _rewrite(path: Path, id_field: str, apply: bool) -> list[str]:
    rows = yaml.safe_load(path.read_text()) or []
    changed: list[str] = []
    for row in rows:
        if row.get(id_field) in OLD_IDS:
            changed.append(f"{row.get('variant_id') or row.get('id')}: {row[id_field]} -> {NEW_ID}")
            row[id_field] = NEW_ID
    if changed and apply:
        header = ""
        text = path.read_text()
        if text.startswith("#"):
            header = "\n".join(line for line in text.splitlines() if line.startswith("#")) + "\n\n"
        path.write_text(header + yaml.dump(rows, allow_unicode=True, sort_keys=False))
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    print(f"{'APPLYING' if args.apply else 'DRY RUN'}\n")

    variant_changes = _rewrite(VARIANTS_PATH, "engine_family", args.apply)
    print(f"{VARIANTS_PATH.relative_to(REPO_ROOT)}:")
    for c in variant_changes:
        print(f"  {c}")

    fitment_changes = _rewrite(FITMENT_PATH, "engine_family", args.apply)
    print(f"\n{FITMENT_PATH.relative_to(REPO_ROOT)}:")
    for c in fitment_changes:
        print(f"  {c}")

    print(f"\nTOTAL: {len(variant_changes) + len(fitment_changes)} row(s) repointed")
    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
