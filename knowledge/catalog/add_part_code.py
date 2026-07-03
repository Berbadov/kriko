"""add_part_code.py — procedurally add a universal part-code field to a
variants YAML.

"Universal" part axes (cooling_code, electrical_code, body_code — one per
model generation, not per engine/gearbox) apply identically to every variant
row. Hand-editing every row to add a new one is exactly the kind of YAML
surgery CLAUDE.md forbids — this is a scripted, idempotent transformation
instead, so it's reproducible and auditable like the rest of the pipeline.

Usage:
    python -m knowledge.catalog.add_part_code \
        --make volkswagen --model golf_7 --field body_code --value golf7_body
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
VARIANTS_DIR = REPO_ROOT / "backend" / "data" / "variants"


def run(make: str, model: str, field: str, value: str, dry_run: bool = False) -> None:
    path = VARIANTS_DIR / f"{make}_{model}.yaml"
    if not path.exists():
        raise SystemExit(f"Variants YAML not found: {path}")

    rows: list[dict] = yaml.safe_load(path.read_text()) or []
    if not rows:
        raise SystemExit(f"No variant rows in {path}")

    changed = 0
    for row in rows:
        if row.get(field) != value:
            row[field] = value
            changed += 1

    if changed == 0:
        print(f"No change — every row already has {field}: {value}")
        return

    print(f"{'Would set' if dry_run else 'Setting'} {field}: {value} on "
          f"{changed}/{len(rows)} row(s) in {path.relative_to(REPO_ROOT)}")
    if dry_run:
        return

    path.write_text(yaml.dump(rows, allow_unicode=True, sort_keys=False))
    print(f"Wrote {path.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make", required=True)
    parser.add_argument("--model", required=True, help="Model key matching variants YAML (e.g. golf_7)")
    parser.add_argument("--field", required=True, help="Field name to set, e.g. body_code")
    parser.add_argument("--value", required=True, help="Value to set on every row")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.make.lower(), args.model.lower(), args.field, args.value, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
