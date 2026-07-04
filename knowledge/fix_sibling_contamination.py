"""fix_sibling_contamination.py — one-off cleanup of sibling-code-contaminated
claims already written to backend/data/parts/**/*.yaml.

docs/design_flaws.md Flaw 1: promote.py's deterministic gate_variant bypass
checks the FULL source page for a code match, so a DSG-comparison-style
article naming several sibling codes (DQ200/DQ250/DQ381, K9K/H4D/H5D/H5H,
EA211/EA288/EA888, DC4/DW5/DW6) lets an off-topic claim about one sibling
ride the bypass into a different sibling's part file. promote.py and
validate_part_yaml.py now guard against this going forward (same
knowledge.stoplists.mentions_sibling_code check as this script); this is the
one-time pass over data written before that guard existed.

This DELETES the contaminated claim from its current (wrong) file. It does
NOT reroute/merge it into the sibling's file: spot-checking the live catalog
showed the sibling file almost always already has its own independently
sourced claim covering the same failure (e.g. dq200.yaml already has its own
P189C/P17BF accumulator-pressure claims, sourced separately from the ones
wrongly filed under dq381.yaml) — rerouting would just create duplicates.

Usage:
    python -m knowledge.fix_sibling_contamination              # dry run — report only
    python -m knowledge.fix_sibling_contamination --apply       # write changes
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from knowledge.stoplists import mentions_sibling_code

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"


def _claim_text(claim: dict) -> str:
    return " ".join(str(claim.get(f, "") or "") for f in ("title", "rationale"))


def _clean_file(path: Path, part_id: str, apply: bool) -> list[dict]:
    """Return the list of removed claim dicts (title + claim_key) for this file."""
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims", [])
    if not isinstance(claims, list):
        return []

    kept: list[dict] = []
    removed: list[dict] = []
    for claim in claims:
        if isinstance(claim, dict) and mentions_sibling_code(_claim_text(claim), part_id):
            removed.append(claim)
        else:
            kept.append(claim)

    if removed and apply:
        data["claims"] = kept
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))

    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    print(f"{'APPLYING' if args.apply else 'DRY RUN'}\n")

    total_removed = 0
    total_files = 0
    for path in sorted(PARTS_DIR.glob("**/*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        part_id = data.get("part_id", path.stem)
        removed = _clean_file(path, part_id, args.apply)
        if removed:
            total_files += 1
            total_removed += len(removed)
            print(f"  {path.relative_to(REPO_ROOT)} ({part_id}):")
            for claim in removed:
                print(f"      - {claim.get('claim_key', '?')!r}: {claim.get('title', '')!r}")

    print(f"\n  TOTAL: {total_removed} contaminated claim(s) removed across {total_files} file(s)")

    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
