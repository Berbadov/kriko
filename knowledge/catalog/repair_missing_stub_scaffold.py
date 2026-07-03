"""repair_missing_stub_scaffold.py — one-time repair for parts written via
`knowledge.auto --part` before run_part() called _ensure_part_stub.

Reconstructs part_id/part_type/display_name/manufacturer/known_also_as using
the exact same generation logic as _ensure_part_stub (auto.py), then merges
them in front of the existing (claims-only) file content. Claims themselves
are untouched.

Usage:
    python -m knowledge.catalog.repair_missing_stub_scaffold \
        --file backend/data/parts/electrical/megane4_elec.yaml \
        --part-id megane4_elec --part-type electrical \
        --make renault --model megane_4 --apply
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent


def _generate_scaffold(part_id: str, part_type: str, make: str, model: str) -> dict:
    make_pretty = make.replace("_", " ").title()
    model_pretty = model.replace("_", " ").title()

    if part_type == "electrical":
        display_name = f"{make_pretty} {model_pretty} Electrical Systems"
        known_also_as = [
            f"{make_pretty} {model_pretty} electrical",
            f"{make_pretty} {model_pretty} electronics",
            f"{make_pretty} {model_pretty} battery",
        ]
    elif part_type == "cooling":
        display_name = f"{make_pretty} {model_pretty} Cooling System"
        known_also_as = [
            f"{make_pretty} {model_pretty} cooling",
            f"{make_pretty} {model_pretty} coolant",
            f"{make_pretty} {model_pretty} thermostat",
        ]
    elif part_type == "body":
        display_name = f"{make_pretty} {model_pretty} Body & Water Sealing"
        known_also_as = [
            f"{make_pretty} {model_pretty} body",
            f"{make_pretty} {model_pretty} boot leak",
            f"{make_pretty} {model_pretty} water ingress",
        ]
    else:
        raise ValueError(f"engine/transmission need real codes/descs from variants — not supported here, part_type={part_type!r}")

    return {
        "part_id": part_id,
        "part_type": part_type,
        "display_name": display_name,
        "manufacturer": make,
        "known_also_as": known_also_as,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True)
    parser.add_argument("--part-id", required=True)
    parser.add_argument("--part-type", required=True, choices=["electrical", "cooling", "body"])
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

    scaffold = _generate_scaffold(args.part_id, args.part_type, args.make, args.model)
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
