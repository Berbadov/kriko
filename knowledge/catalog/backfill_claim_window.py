"""backfill_claim_window.py — set a model-year window on one existing claim.

Companion to backfill_part_field.py (which sets a top-level field on a part
file). This targets a single claim *inside* a part file's `claims:` list,
located by `claim_key`, and sets its
`applies_when.applies_year_from` / `applies_year_to` model-year window, leaving
every other applies_when key (e.g. min_mileage_km) untouched.

This is the "backfill with human sign-off" write path the scalability rule
requires (no hand-edited YAML, no hardcoded car data in Python): the operator
supplies a reviewed (claim_key -> year window) mapping as arguments. It is also
the mechanism the recall importer reuses to stamp windows onto emitted claims.

A None bound clears/omits that side (open-ended), so re-runs are idempotent.

Usage:
    python -m knowledge.catalog.backfill_claim_window \
        --file backend/data/parts/engine/k9k.yaml \
        --claim-key k9k_egr_cooler_crack --year-from 2019 --year-to 2022 \
        --apply

    # open-ended (fault introduced from MY2023 onward):
    python -m knowledge.catalog.backfill_claim_window \
        --file backend/data/parts/engine/k9k.yaml \
        --claim-key k9k_adas_fault --year-from 2023 --apply
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent


def set_claim_window(
    data: dict,
    claim_key: str,
    year_from: int | None,
    year_to: int | None,
) -> bool:
    """Set the applies_year_from/to window on the claim with `claim_key`.

    A None bound removes that side (open-ended). Preserves other applies_when
    keys. Returns True if the claim was found, False otherwise (no mutation).
    """
    for claim in data.get("claims", []) or []:
        if claim.get("claim_key") != claim_key:
            continue
        aw = claim.get("applies_when") or {}
        for name, val in (("applies_year_from", year_from), ("applies_year_to", year_to)):
            if val is None:
                aw.pop(name, None)
            else:
                aw[name] = val
        if aw:
            claim["applies_when"] = aw
        else:
            claim.pop("applies_when", None)
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", required=True, help="Part YAML path")
    parser.add_argument("--claim-key", required=True, help="claim_key of the claim to scope")
    parser.add_argument("--year-from", type=int, default=None, help="Inclusive lower model-year bound")
    parser.add_argument("--year-to", type=int, default=None, help="Inclusive upper model-year bound (omit for open-ended)")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    if args.year_from is None and args.year_to is None:
        parser.error("give at least one of --year-from / --year-to")
    if args.year_from is not None and args.year_to is not None and args.year_from > args.year_to:
        parser.error(f"--year-from ({args.year_from}) must be <= --year-to ({args.year_to})")

    path = Path(args.file)
    if not path.is_absolute():
        path = REPO_ROOT / args.file
    data = yaml.safe_load(path.read_text())

    window = f"{args.year_from or '…'}–{args.year_to or '…'}"
    print(f"{'APPLYING' if args.apply else 'DRY RUN'} — window MY{window} on {args.claim_key} in {args.file}\n")

    found = set_claim_window(data, args.claim_key, args.year_from, args.year_to)
    if not found:
        parser.error(f"no claim with claim_key {args.claim_key!r} in {args.file}")

    claim = next(c for c in data["claims"] if c.get("claim_key") == args.claim_key)
    print(f"  {args.claim_key}: applies_when = {claim.get('applies_when', {})}")

    if args.apply:
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
        print("\nWritten. Re-run knowledge.parts.validate_part_yaml before syncing.")
    else:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
