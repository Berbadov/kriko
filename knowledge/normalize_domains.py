"""normalize_domains.py — one-off retroactive cleanup of malformed claim domains.

The extraction LLM has drifted into inventing domain values ("cooling
system", "HVAC", "mechanical", "steering", "safety") and multi-value joins
("engine|brakes|suspension", "turbocharger/fuel system") across
backend/data/parts/**/*.yaml, confirmed across ea888/h5d_100/megane4_body/
dc4/clio5_body and others. See knowledge/domains.py for why this matters
(resolver.py's domain-grouping does an exact string match).

knowledge.extract now coerces domain at extraction time for future runs
(CandidateClaim field_validator); this script fixes already-written data.

Usage:
    python -m knowledge.normalize_domains              # dry run — report only
    python -m knowledge.normalize_domains --apply       # write changes
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from knowledge.domains import normalize_domain

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"
CLAIMS_DIR = REPO_ROOT / "backend" / "data" / "claims"


def _normalize_file(path: Path, apply: bool) -> list[tuple[str, str, str]]:
    """Return [(claim_key_or_title, old_domain, new_domain), ...] for changed claims."""
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims") if isinstance(data, dict) and "claims" in data else data
    if not isinstance(claims, list):
        return []

    changes: list[tuple[str, str, str]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        old = claim.get("domain", "")
        new = normalize_domain(old)
        if new != old:
            label = claim.get("claim_key") or claim.get("title", "")[:40]
            changes.append((label, old, new))
            claim["domain"] = new

    if changes and apply:
        if isinstance(data, dict) and "claims" in data:
            data["claims"] = claims
            path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
        else:
            path.write_text(yaml.dump(claims, allow_unicode=True, sort_keys=False))

    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    print(f"{'APPLYING' if args.apply else 'DRY RUN'}\n")

    total_changed = 0
    total_claims = 0
    for base_dir in (PARTS_DIR, CLAIMS_DIR):
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.glob("**/*.yaml")):
            changes = _normalize_file(path, args.apply)
            total_claims += len(changes)
            if changes:
                total_changed += 1
                print(f"  {path.relative_to(REPO_ROOT)}:")
                for label, old, new in changes:
                    print(f"      {label!r}: {old!r} -> {new!r}")

    print(f"\n  TOTAL: {total_claims} claim(s) normalized across {total_changed} file(s)")

    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
