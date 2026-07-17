"""backfill_claim_mileage.py — set a min_mileage_km gate on claims.

Companion to backfill_claim_window.py. Two modes:

  * manual — set one claim's `applies_when.min_mileage_km` by claim_key
    (operator supplies a reviewed value), leaving other applies_when keys intact;
  * --auto — run ground_mileage_threshold() over every servable claim's text and
    propose a grounded threshold for each, as a review table. Dry-run by default;
    --apply writes. This is the "backfill with sign-off" path the no-hand-YAML
    rule requires: the extraction is deterministic and grounded, the human
    approves the table before it is written.

A None value clears the bound (idempotent re-runs).

Usage:
    # auto-propose across the whole corpus (dry run), then apply:
    python -m knowledge.catalog.backfill_claim_mileage --auto
    python -m knowledge.catalog.backfill_claim_mileage --auto --apply

    # set one claim by hand:
    python -m knowledge.catalog.backfill_claim_mileage \
        --file backend/data/parts/transmission/dq200.yaml \
        --claim-key dq200_clutch_wear --min-mileage-km 60000 --apply
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from knowledge.ground_mileage_threshold import ground_mileage_threshold

REPO_ROOT = Path(__file__).parent.parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"
SERVABLE = {"review", "verified"}


def set_claim_mileage(data: dict, claim_key: str, min_mileage_km: int | None) -> bool:
    """Set applies_when.min_mileage_km on the claim with `claim_key`.

    A None value removes the bound. Preserves other applies_when keys. Returns
    True if the claim was found, False otherwise (no mutation).
    """
    for claim in data.get("claims", []) or []:
        if claim.get("claim_key") != claim_key:
            continue
        aw = claim.get("applies_when") or {}
        if min_mileage_km is None:
            aw.pop("min_mileage_km", None)
        else:
            aw["min_mileage_km"] = min_mileage_km
        if aw:
            claim["applies_when"] = aw
        else:
            claim.pop("applies_when", None)
        return True
    return False


def _claim_text(claim: dict) -> str:
    return f"{claim.get('title', '')} {claim.get('rationale', '')}"


def _auto(apply: bool) -> None:
    proposals: list[tuple[Path, dict, str, int]] = []
    for path in sorted(PARTS_DIR.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        for claim in data.get("claims", []) or []:
            if claim.get("status") not in SERVABLE:
                continue
            if (claim.get("applies_when") or {}).get("min_mileage_km") is not None:
                continue  # already gated — don't overwrite a reviewed value
            km = ground_mileage_threshold(_claim_text(claim))
            if km is not None:
                proposals.append((path, data, claim.get("claim_key", ""), km))

    print(f"{'APPLYING' if apply else 'DRY RUN'} — {len(proposals)} grounded "
          f"min_mileage_km proposal(s):\n")
    for path, _, key, km in proposals:
        print(f"  {km:>7,} km  {key}  ({path.name})")

    if not apply:
        print("\nDry run — no files written. Re-run with --apply to write.")
        return

    touched: dict[Path, dict] = {}
    for path, data, key, km in proposals:
        set_claim_mileage(data, key, km)
        touched[path] = data
    for path, data in touched.items():
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
    print(f"\nWritten {len(touched)} file(s). "
          f"Re-run knowledge.parts.validate_part_yaml before syncing.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--auto", action="store_true",
                        help="Propose grounded thresholds across all servable claims")
    parser.add_argument("--file", help="Part YAML path (manual mode)")
    parser.add_argument("--claim-key", help="claim_key to set (manual mode)")
    parser.add_argument("--min-mileage-km", type=int, default=None,
                        help="Threshold to set (manual mode); omit to clear")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default: dry run)")
    args = parser.parse_args()

    if args.auto:
        _auto(args.apply)
        return

    if not args.file or not args.claim_key:
        parser.error("give --auto, or both --file and --claim-key for manual mode")

    path = Path(args.file)
    if not path.is_absolute():
        path = REPO_ROOT / args.file
    data = yaml.safe_load(path.read_text())

    print(f"{'APPLYING' if args.apply else 'DRY RUN'} — "
          f"min_mileage_km={args.min_mileage_km} on {args.claim_key} in {args.file}\n")
    if not set_claim_mileage(data, args.claim_key, args.min_mileage_km):
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
