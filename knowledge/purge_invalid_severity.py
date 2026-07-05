"""purge_invalid_severity.py — reject claims with a severity outside high|medium|low.

extract.py's CandidateClaim.severity used to be a bare `str`, so a
hallucinated value (e.g. "unknown") could flow all the way to a written part
YAML undetected until knowledge.parts.validate_part_yaml caught it as a
schema error. The extraction schema is now constrained to
Literal["high", "medium", "low"] so this can't recur going forward; this
script is the one-time retroactive cleanup for whatever already slipped
through, mirroring purge_forums.py / purge_german.py.

Usage:
    python -m knowledge.purge_invalid_severity              # dry run
    python -m knowledge.purge_invalid_severity --apply       # write changes
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from knowledge.parts.validate_part_yaml import VALID_SEVERITIES

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    print(f"{'APPLYING' if args.apply else 'DRY RUN'} — rejecting claims with invalid severity\n")

    total = 0
    for path in sorted(PARTS_DIR.glob("**/*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        claims = data.get("claims") if "claims" in data else data
        if not isinstance(claims, list):
            continue

        touched = []
        for claim in claims:
            if claim.get("severity") in VALID_SEVERITIES:
                continue
            touched.append(f"{claim.get('claim_key')} [severity={claim.get('severity')!r}, was status={claim.get('status')!r}]")
            claim["status"] = "rejected"
            # Schema requires a valid enum value even on a dead claim; the
            # value is moot once rejected, so normalize rather than leave
            # the YAML permanently failing validation.
            claim["severity"] = "low"

        if touched:
            print(f"  {path.relative_to(REPO_ROOT)}: {len(touched)} claim(s) rejected")
            for t in touched:
                print(f"      {t}")
            if args.apply:
                if "claims" in data:
                    data["claims"] = claims
                    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
                else:
                    path.write_text(yaml.dump(claims, allow_unicode=True, sort_keys=False))
        total += len(touched)

    print(f"\n  TOTAL: {total} claim(s) rejected")
    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
