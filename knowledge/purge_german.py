"""purge_german.py — retroactively reject claims whose text is untranslated German.

knowledge.stoplists.is_german_text() now runs at fetch time (knowledge.sources.
curated._fetch_entry) so new German-language pages get dropped before they ever
reach extraction. This script cleans up what was already extracted before that
gate existed: claims whose title/rationale/inspection_advice are themselves in
German (the extraction LLM echoed source text verbatim instead of translating
it — see docs/pipeline_postmortem.md and stoplists.is_german_text's docstring).

Sets status: rejected on affected claims — the documented mechanism
(knowledge/promote.py) for permanently burying a claim so it's never re-added
by a future pipeline run and never served (rejected is not in the servable set).
Content is preserved for audit, not deleted, mirroring knowledge/purge_forums.py.

Usage:
    python -m knowledge.purge_german              # dry run — report only
    python -m knowledge.purge_german --apply       # write changes
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from knowledge.stoplists import is_german_text

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"
CLAIMS_DIR = REPO_ROOT / "backend" / "data" / "claims"


def _claim_text(claim: dict) -> str:
    return " ".join(
        filter(None, [claim.get("title", ""), claim.get("rationale", ""), claim.get("inspection_advice", "")])
    )


def _purge_claim_file(path: Path, apply: bool) -> list[str]:
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims") if "claims" in data else data
    if not isinstance(claims, list):
        return []

    touched = []
    changed = False

    for claim in claims:
        if claim.get("status") == "rejected":
            continue
        if not is_german_text(_claim_text(claim)):
            continue
        touched.append(f"{claim.get('claim_key')} [{claim.get('status')}]")
        claim["status"] = "rejected"
        changed = True

    if changed and apply:
        if "claims" in data:
            data["claims"] = claims
            path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
        else:
            path.write_text(yaml.dump(claims, allow_unicode=True, sort_keys=False))

    return touched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    print(f"{'APPLYING' if args.apply else 'DRY RUN'} — rejecting German-language claims\n")

    total = 0
    for base in (PARTS_DIR, CLAIMS_DIR):
        if not base.exists():
            continue
        pattern = "**/*.yaml" if base is PARTS_DIR else "*.yaml"
        for path in sorted(base.glob(pattern)):
            touched = _purge_claim_file(path, args.apply)
            if touched:
                print(f"  {path.relative_to(REPO_ROOT)}: {len(touched)} claim(s) rejected")
                for t in touched:
                    print(f"      {t}")
            total += len(touched)

    print(f"\n  TOTAL: {total} claim(s) rejected")
    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
