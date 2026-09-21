"""validate_fitment.py — validate fitment YAMLs against variant catalog.

Checks:
- Every fitment variant_id exists in the corresponding variants YAML.
- engine_family + transmission_code are non-empty strings.
- Fitment engine_family matches the variant's engine_code (lowercase) — if the
  variant has an engine_code set and it differs from engine_family, print a warning
  (may be intentional for cross-brand aliases like 1.4 TSI → ea211).
- Every variant in the variants YAML has a fitment entry (warns if missing).

Usage:
    python -m packs.cars.pipeline.fitment.validate_fitment
    python -m packs.cars.pipeline.fitment.validate_fitment packs/cars/data/fitment/renault_megane_4.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from packs.cars.pipeline.paths import REPO_ROOT
FITMENT_DIR  = REPO_ROOT / "packs" / "cars" / "data" / "fitment"
VARIANTS_DIR = REPO_ROOT / "packs" / "cars" / "data" / "variants"


def _load_variants(make_model: str) -> dict[str, dict]:
    """Load variants for a model file stem (e.g. 'renault_megane_4')."""
    path = VARIANTS_DIR / f"{make_model}.yaml"
    if not path.exists():
        return {}
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {r["id"]: r for r in rows}


def validate_fitment_file(fitment_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        rows = yaml.safe_load(fitment_path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as e:
        return [f"{fitment_path}: YAML parse error: {e}"]

    if not isinstance(rows, list):
        return [f"{fitment_path}: root must be a list"]

    make_model = fitment_path.stem
    variants = _load_variants(make_model)
    if not variants:
        errors.append(
            f"{fitment_path}: could not load corresponding variants file "
            f"{VARIANTS_DIR / make_model}.yaml"
        )

    seen_variant_ids: set[str] = set()
    for i, row in enumerate(rows):
        loc = f"{fitment_path}[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{loc}: entry must be a mapping")
            continue

        vid = row.get("variant_id", "")
        if not vid:
            errors.append(f"{loc}: missing variant_id")
            continue

        if vid in seen_variant_ids:
            errors.append(f"{loc}: duplicate variant_id {vid!r}")
        seen_variant_ids.add(vid)

        if variants and vid not in variants:
            errors.append(f"{loc}: variant_id {vid!r} not found in variants YAML")

        engine_family = row.get("engine_family", "")
        if not engine_family:
            errors.append(f"{loc}: missing engine_family")

        transmission_code = row.get("transmission_code", "")
        if not transmission_code:
            errors.append(f"{loc}: missing transmission_code")

        # Advisory: if engine_code is set in variant and differs from engine_family
        if variants and vid in variants:
            variant = variants[vid]
            ec = (variant.get("engine_code") or "").lower()
            if ec and engine_family and ec != engine_family:
                print(
                    f"  WARN {loc}: engine_family={engine_family!r} differs from "
                    f"variant engine_code={ec!r} (may be intentional cross-brand alias)"
                )

    # Check for variants missing a fitment entry
    for vid in sorted(set(variants) - seen_variant_ids):
        errors.append(
            f"{fitment_path}: variant {vid!r} has no fitment entry — "
            f"add it or it will get no part claims"
        )

    return errors


def main() -> None:
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        paths = sorted(FITMENT_DIR.glob("*.yaml"))

    if not paths:
        print(f"No fitment YAML files found under {FITMENT_DIR}")
        sys.exit(1)

    print(f"Validating {len(paths)} fitment YAML file(s)…")
    total_errors = 0
    for path in sorted(paths):
        errors = validate_fitment_file(path)
        for e in errors:
            print(f"ERROR: {e}")
        total_errors += len(errors)

    if total_errors == 0:
        print("OK — all fitment files valid.")
    else:
        print(f"\n{total_errors} error(s) found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
