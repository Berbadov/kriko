"""strip_fitment_field.py — remove a stale key from every row of a fitment YAML.

write_fitment_yaml() (knowledge/catalog/discover.py) deliberately preserves
any extra key already present in a fitment file that its own generated rows
don't produce, treating it as hand-curated. That's correct for genuinely
hand-added fields, but it also means a stale/wrong key (e.g. a placeholder
that was never backed by a real variants field) survives every regeneration
forever unless explicitly stripped.

Usage:
    python -m knowledge.catalog.strip_fitment_field \
        --make renault --model megane_4 --field cooling_code
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
FITMENT_DIR = REPO_ROOT / "backend" / "data" / "fitment"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make", required=True)
    parser.add_argument("--model", required=True, help="Model key matching fitment YAML (e.g. megane_4)")
    parser.add_argument("--field", required=True, help="Field name to remove, e.g. cooling_code")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = FITMENT_DIR / f"{args.make}_{args.model}.yaml"
    rows = yaml.safe_load(path.read_text()) or []

    touched = sum(1 for r in rows if args.field in r)
    if not touched:
        print(f"No rows in {path} have '{args.field}'. Nothing to do.")
        return

    if args.dry_run:
        print(f"DRY RUN — would remove '{args.field}' from {touched}/{len(rows)} row(s) in {path}")
        return

    for r in rows:
        r.pop(args.field, None)

    path.write_text(yaml.dump(rows, allow_unicode=True, sort_keys=False))
    print(f"Removed '{args.field}' from {touched}/{len(rows)} row(s) in {path}")


if __name__ == "__main__":
    main()
