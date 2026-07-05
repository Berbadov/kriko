"""purge_forums.py — one-off retroactive removal of forum-domain sources.

Forum threads read like chronic-pattern evidence once extracted, but they're
frequently a single poster's one-time incident (see pipeline_postmortem).
knowledge.stoplists.FORUM_DOMAINS now blocks these domains from future
discovery (wired into knowledge.auto's Exa exclude list); this script cleans
up what was already ingested before that block existed:

  1. Strip forum-domain sources from every part-claim's `sources:` list and
     recompute score/status/confidence from what's left (same thresholds as
     knowledge.promote — a claim never gets stronger from losing a source).
  2. Delete forum-domain entries from the curated source YAMLs so they stop
     counting as "already seen" and stop showing up in any review tooling.

Usage:
    python -m knowledge.purge_forums              # dry run — report only
    python -m knowledge.purge_forums --apply       # write changes
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from knowledge.promote import SCORE_REVIEW, SCORE_VERIFY
from knowledge.stoplists import FORUM_DOMAINS

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"
CLAIMS_DIR = REPO_ROOT / "backend" / "data" / "claims"
CURATED_DIR = Path(__file__).parent / "sources" / "curated"


def _is_forum(source: dict) -> bool:
    domain = (source.get("source_domain") or source.get("site_or_channel") or "").lower()
    return domain in FORUM_DOMAINS


def _recompute_status(claim: dict, new_source_count: int) -> tuple[str, float]:
    if claim.get("severity") == "high":
        status = "review" if new_source_count >= SCORE_REVIEW else "held"
    elif new_source_count >= SCORE_VERIFY:
        status = "verified"
    elif new_source_count >= SCORE_REVIEW:
        status = "review"
    else:
        status = "held"
    confidence = min(0.9, max(0.6, new_source_count / 2)) if new_source_count > 0 else 0.0
    return status, round(confidence, 2)


def _purge_claim_file(path: Path, apply: bool) -> dict:
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims") if "claims" in data else data
    if not isinstance(claims, list):
        return {"sources_removed": 0, "claims_touched": 0, "claims_downgraded": 0}

    stats = {"sources_removed": 0, "claims_touched": 0, "claims_downgraded": 0}
    changed = False

    for claim in claims:
        sources = claim.get("sources") or []
        kept = [s for s in sources if not _is_forum(s)]
        removed = len(sources) - len(kept)
        if removed == 0:
            continue

        stats["sources_removed"] += removed
        stats["claims_touched"] += 1
        old_status = claim.get("status", "held")

        claim["sources"] = kept
        if claim.get("kind") != "maintenance":
            new_status, new_confidence = _recompute_status(claim, len(kept))
            if new_status != old_status:
                stats["claims_downgraded"] += 1
            claim["status"] = new_status
            claim["confidence"] = new_confidence
        changed = True

    if changed and apply:
        if "claims" in data:
            data["claims"] = claims
            path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
        else:
            path.write_text(yaml.dump(claims, allow_unicode=True, sort_keys=False))

    return stats


def _purge_curated_file(path: Path, apply: bool) -> int:
    entries = yaml.safe_load(path.read_text()) or []
    kept = [e for e in entries if (e.get("site_or_channel") or "").lower() not in FORUM_DOMAINS]
    removed = len(entries) - len(kept)
    if removed and apply:
        path.write_text(yaml.dump(kept, allow_unicode=True, sort_keys=False))
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    print(f"{'APPLYING' if args.apply else 'DRY RUN'} — {len(FORUM_DOMAINS)} forum domains\n")

    print("── Part claim files ──────────────────────────────────────────")
    totals = {"sources_removed": 0, "claims_touched": 0, "claims_downgraded": 0}
    for path in sorted(PARTS_DIR.glob("**/*.yaml")):
        stats = _purge_claim_file(path, args.apply)
        if stats["claims_touched"]:
            print(
                f"  {path.relative_to(REPO_ROOT)}: "
                f"{stats['sources_removed']} source(s) removed from "
                f"{stats['claims_touched']} claim(s), "
                f"{stats['claims_downgraded']} status change(s)"
            )
        for k in totals:
            totals[k] += stats[k]

    if CLAIMS_DIR.exists():
        for path in sorted(CLAIMS_DIR.glob("*.yaml")):
            stats = _purge_claim_file(path, args.apply)
            if stats["claims_touched"]:
                print(
                    f"  {path.relative_to(REPO_ROOT)}: "
                    f"{stats['sources_removed']} source(s) removed from "
                    f"{stats['claims_touched']} claim(s), "
                    f"{stats['claims_downgraded']} status change(s)"
                )
            for k in totals:
                totals[k] += stats[k]

    print(
        f"\n  TOTAL: {totals['sources_removed']} source(s) removed, "
        f"{totals['claims_touched']} claim(s) touched, "
        f"{totals['claims_downgraded']} status downgrade(s)"
    )

    print("\n── Curated source YAMLs ──────────────────────────────────────")
    curated_total = 0
    if CURATED_DIR.exists():
        for path in sorted(CURATED_DIR.glob("*.yaml")):
            removed = _purge_curated_file(path, args.apply)
            if removed:
                print(f"  {path.relative_to(REPO_ROOT)}: {removed} entry(ies) removed")
            curated_total += removed
    print(f"\n  TOTAL: {curated_total} curated entry(ies) removed")

    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
