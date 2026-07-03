"""backfill_part_field.py — set a missing top-level field on existing part YAML(s).

Companion to add_part_code.py (which adds a field to every row of a variants
YAML). This targets a single top-level field on one or more already-written
part stub files — e.g. `manufacturer`, dropped by a since-fixed bug in
knowledge.auto._ensure_part_stub for the cooling/electrical/body stub
branches.

Usage:
    python -m knowledge.catalog.backfill_part_field \
        --file backend/data/parts/body/golf7_body.yaml --field manufacturer --value volkswagen \
        --file backend/data/parts/body/megane4_body.yaml --field manufacturer --value renault \
        --apply
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", action="append", required=True, help="Part YAML path (repeatable)")
    parser.add_argument("--field", required=True, help="Top-level field name")
    parser.add_argument("--value", action="append", required=True, help="Value for the matching --file (repeatable, same order)")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    if len(args.file) != len(args.value):
        parser.error("--file and --value must be given the same number of times, in matching order")

    print(f"{'APPLYING' if args.apply else 'DRY RUN'} — backfilling '{args.field}'\n")
    for file_arg, value in zip(args.file, args.value):
        path = Path(file_arg)
        if not path.is_absolute():
            path = REPO_ROOT / file_arg
        data = yaml.safe_load(path.read_text())
        if args.field in data:
            print(f"  {file_arg}: already has '{args.field}' = {data[args.field]!r}, skipping")
            continue
        print(f"  {file_arg}: set {args.field} = {value!r}")
        if args.apply:
            ordered = {"part_id": data["part_id"], "part_type": data["part_type"], "display_name": data["display_name"]}
            ordered[args.field] = value
            for k, v in data.items():
                if k not in ordered:
                    ordered[k] = v
            path.write_text(yaml.dump(ordered, allow_unicode=True, sort_keys=False))

    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
