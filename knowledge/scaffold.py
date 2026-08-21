"""scaffold.py — bootstrap YAML files for a new car model.

Creates the two files required before running the knowledge pipeline:
  - backend/data/variants/{make}_{model}_{gen}.yaml  (template — fill in real variants)
  - knowledge/sources/curated/{make}_{model}_{gen}.yaml  (empty list)

Usage:
    python -m knowledge.scaffold renault megane 4
    python -m knowledge.scaffold toyota corolla e210
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT    = Path(__file__).parent.parent
VARIANTS_DIR = REPO_ROOT / "backend" / "data" / "variants"
CURATED_DIR  = Path(__file__).parent / "sources" / "curated"

# Template text for the variants YAML.  Written verbatim so comments and field
# order are preserved — yaml.dump would strip both.
_VARIANTS_TEMPLATE = """\
# {make_title} {model_title} {gen_upper} — Turkish market variant catalog
# Hand-written from manufacturer spec sheets + press releases.
# Invariant: variant IDs are stable forever — add new variants, never rename live ones.
#
# ID format: {{model}}_{{engine_code}}_{{power_hp}}[_{{tx_suffix}}]
# tx_suffix examples: edc, cvt, mt  (omit for the dominant transmission of that line)
#
# Required fields: id, make, model, generation, engine_code, fuel,
#   displacement_cc, power_min_hp, power_max_hp, transmission,
#   year_from, year_to, market
# Optional: notes

- id: {model}_{gen}_PLACEHOLDER
  make: {make}
  model: {model}
  generation: "{gen_upper}"
  engine_code: ENGINE_CODE        # e.g. H5F, K9K, 2ZR-FE
  fuel: petrol                    # petrol | diesel | hybrid | electric
  displacement_cc: 1000           # integer
  power_min_hp: 90                # lower bound of power range for this trim
  power_max_hp: 90                # upper bound (same as min if single power level)
  transmission: manual            # manual | automatic
  year_from: 2020
  year_to: null                   # null = still in production
  market: TR
  notes: "Fill in a human-readable description"
"""


def _make_variants_content(make: str, model: str, gen: str) -> str:
    return _VARIANTS_TEMPLATE.format(
        make=make,
        model=model,
        gen=gen,
        gen_upper=gen.upper(),
        make_title=make.title(),
        model_title=model.title(),
    )


def run(make: str, model: str, gen: str) -> None:
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)

    slug = f"{make}_{model}_{gen}"
    variants_path = VARIANTS_DIR / f"{slug}.yaml"
    curated_path  = CURATED_DIR  / f"{slug}.yaml"

    errors: list[str] = []
    if variants_path.exists():
        errors.append(f"  {variants_path.relative_to(REPO_ROOT)} already exists")
    if curated_path.exists():
        errors.append(f"  {curated_path.relative_to(REPO_ROOT)} already exists")
    if errors:
        print("ERROR — refusing to overwrite existing files:")
        for e in errors:
            print(e)
        sys.exit(1)

    variants_path.write_text(_make_variants_content(make, model, gen))
    curated_path.write_text("[]\n")

    print(f"Created {variants_path.relative_to(REPO_ROOT)}")
    print(f"Created {curated_path.relative_to(REPO_ROOT)}")
    print(f"""
Next steps:
  1. Edit {variants_path.relative_to(REPO_ROOT)}
       Fill in real variant rows — one entry per engine/power/transmission combo.
  2. python -m knowledge.auto {make} {model} {gen} --max-sources 60
       Discovers sources automatically (Exa + YouTube) and runs extraction.
  3. docker compose -f deploy/docker-compose.yml restart api
       Syncs the new claims to the database.

Tip: to add sources manually instead of auto-discovering them, see docs/historical/SCAFFOLD.md.
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap YAML files for a new car model."
    )
    parser.add_argument("make",  help="Car make, e.g. renault, toyota")
    parser.add_argument("model", help="Car model, e.g. megane, corolla")
    parser.add_argument("gen",   help="Generation key, e.g. 4, e210, mk3")
    args = parser.parse_args()
    run(args.make.lower(), args.model.lower(), args.gen.lower())


if __name__ == "__main__":
    main()
