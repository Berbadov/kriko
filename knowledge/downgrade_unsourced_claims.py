"""downgrade_unsourced_claims.py — retroactive fix for the zero-source review bug.

knowledge.promote used to force `severity: high` (or gate_refute-conflicted)
claims to `status: review` regardless of score, so a claim with ZERO sources
that passed gate_support could reach a servable status with an empty
`sources:` list — validate_part_yaml.py flags this as invalid, and a human
reviewer has nothing to actually review. `promote._evaluate_claim` now falls
back to `held` in that case (see knowledge/promote.py); this script applies
the same correction to claims already written before the fix.

Only touches non-maintenance claims in `verified`/`review` status with an
empty `sources` list — downgrades them to `held` (confidence 0.0). Never
touches a claim that already has sources, regardless of severity.

Usage:
    python -m knowledge.downgrade_unsourced_claims              # dry run
    python -m knowledge.downgrade_unsourced_claims --apply       # write changes
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"
CLAIMS_DIR = REPO_ROOT / "backend" / "data" / "claims"


def _fix_file(path: Path, apply: bool) -> list[str]:
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims") if isinstance(data, dict) and "claims" in data else data
    if not isinstance(claims, list):
        return []

    fixed: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        if claim.get("kind") == "maintenance":
            continue
        if claim.get("status") not in ("verified", "review"):
            continue
        if claim.get("sources"):
            continue
        fixed.append(claim.get("claim_key") or claim.get("title", ""))
        claim["status"] = "held"
        claim["confidence"] = 0.0

    if fixed and apply:
        if isinstance(data, dict) and "claims" in data:
            data["claims"] = claims
            path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
        else:
            path.write_text(yaml.dump(claims, allow_unicode=True, sort_keys=False))

    return fixed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    print(f"{'APPLYING' if args.apply else 'DRY RUN'}\n")

    total = 0
    for base_dir in (PARTS_DIR, CLAIMS_DIR):
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.glob("**/*.yaml")):
            fixed = _fix_file(path, args.apply)
            if fixed:
                print(f"  {path.relative_to(REPO_ROOT)}:")
                for key in fixed:
                    print(f"      {key!r} -> held (was servable with no sources)")
            total += len(fixed)

    print(f"\n  TOTAL: {total} claim(s) downgraded to held")
    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
