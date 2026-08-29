"""repair_missing_stub_scaffold.py — one-time repair for parts written before
run_part() ensured a part stub existed (the legacy ops.auto and ops.process
--part paths, both since removed).

Reconstructs part_id/part_type/display_name/manufacturer/known_also_as using
packs.cars.pipeline.parts.search_templates.generate_part_scaffold — the same generation
logic used for new parts — then merges them in
front of the existing (claims-only) file content. Claims themselves are
untouched.

Usage:
    python -m packs.cars.pipeline.catalog.repair_missing_stub_scaffold \
        --file packs/cars/data/parts/electrical/megane4_elec.yaml \
        --part-id megane4_elec --part-type electrical \
        --make renault --model megane_4 --apply

    python -m packs.cars.pipeline.catalog.repair_missing_stub_scaffold \
        --file packs/cars/data/parts/engine/ea888.yaml \
        --part-id ea888 --part-type engine \
        --make volkswagen --model golf_7 --apply
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from packs.cars.pipeline.parts.search_templates import generate_part_scaffold

from packs.cars.pipeline.paths import REPO_ROOT
VARIANTS_DIR = REPO_ROOT / "packs" / "cars" / "data" / "variants"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True)
    parser.add_argument("--part-id", required=True)
    parser.add_argument(
        "--part-type", required=True,
        choices=["engine", "transmission", "cooling", "electrical", "body"],
    )
    parser.add_argument("--make", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_absolute():
        path = REPO_ROOT / args.file
    data = yaml.safe_load(path.read_text()) or {}

    if "part_id" in data:
        print(f"{args.file}: already has part_id={data['part_id']!r} — nothing to repair")
        return

    variants_path = VARIANTS_DIR / f"{args.make}_{args.model}.yaml"
    variants = yaml.safe_load(variants_path.read_text()) if variants_path.exists() else []

    scaffold = generate_part_scaffold(args.part_id, args.part_type, args.make, args.model, variants or [])
    merged = {**scaffold, "claims": data.get("claims", [])}

    print(f"{'APPLYING' if args.apply else 'DRY RUN'} — repairing {args.file}")
    for k, v in scaffold.items():
        print(f"  {k}: {v}")
    print(f"  claims: {len(merged['claims'])} preserved")

    if args.apply:
        path.write_text(yaml.dump(merged, allow_unicode=True, sort_keys=False))
    else:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
