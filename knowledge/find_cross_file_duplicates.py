"""find_cross_file_duplicates.py — report near-duplicate claims across a
model's sibling part files.

Part-centric research is scoped per part (K9K engine, DC4 gearbox, ...), but
extraction from a broad source article isn't scoped to the part being
researched — a "body" search often surfaces engine/transmission content
too (see project memory: "Timing Chain Stretch (R9M 1.6 dCi)" showing up in
megane4_body.yaml almost certainly duplicates something in r9m_130.yaml).
`write_promoted_part_claims`'s near-dup guard only checks *within* the file
being written, so the same issue can end up served twice for one car —
once under its correct part file, once misfiled under another.

This is a REPORT-only tool, not a fixer: deciding which of two claims is the
"right" one to keep (better sourced? more specific?) is a judgment call, and
auto-merging risks silently deleting a genuinely distinct claim on a
title-similarity false positive. Surfaces clusters for a human (or a
follow-up scripted fix once you've decided the merge policy) to act on.

Sibling part files for a model are derived from backend/data/fitment/*.yaml
— every part_id referenced by any variant row of that model (engine_family,
transmission_code, cooling_code, electrical_code, body_code) is a sibling.

Usage:
    python -m knowledge.find_cross_file_duplicates
"""

from __future__ import annotations

from pathlib import Path

import yaml

from knowledge.dedup import title_similar

REPO_ROOT = Path(__file__).parent.parent
FITMENT_DIR = REPO_ROOT / "backend" / "data" / "fitment"
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"

_FITMENT_FIELDS = ("engine_family", "transmission_code", "cooling_code", "electrical_code", "body_code")


def _model_part_ids(fitment_path: Path) -> set[str]:
    rows = yaml.safe_load(fitment_path.read_text()) or []
    ids: set[str] = set()
    for row in rows:
        for field in _FITMENT_FIELDS:
            val = row.get(field)
            if val:
                ids.add(val)
    return ids


def _find_part_file(part_id: str) -> Path | None:
    matches = list(PARTS_DIR.glob(f"*/{part_id}.yaml"))
    return matches[0] if matches else None


def _load_claims(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims", []) if isinstance(data, dict) else data
    return claims if isinstance(claims, list) else []


def main() -> None:
    total_clusters = 0
    for fitment_path in sorted(FITMENT_DIR.glob("*.yaml")):
        model_label = fitment_path.stem
        part_ids = _model_part_ids(fitment_path)

        # (part_id, claim) pairs across every sibling part file for this model.
        entries: list[tuple[str, dict]] = []
        for part_id in sorted(part_ids):
            path = _find_part_file(part_id)
            if not path:
                continue
            for claim in _load_claims(path):
                if isinstance(claim, dict):
                    entries.append((part_id, claim))

        # Compare every cross-file pair (different part_id) for same-domain
        # title similarity. O(n^2) on claims-per-model (tens to low hundreds
        # here) — fine for an offline audit script, not a hot path.
        reported: set[frozenset[str]] = set()
        clusters: list[tuple] = []
        for i, (part_a, claim_a) in enumerate(entries):
            for part_b, claim_b in entries[i + 1:]:
                if part_a == part_b:
                    continue
                if claim_a.get("domain") != claim_b.get("domain"):
                    continue
                if not title_similar(claim_a.get("title", ""), claim_b.get("title", "")):
                    continue
                key = frozenset({claim_a.get("claim_key", ""), claim_b.get("claim_key", "")})
                if key in reported:
                    continue
                reported.add(key)
                clusters.append((part_a, claim_a, part_b, claim_b))

        if not clusters:
            continue

        print(f"\n=== {model_label} — {len(clusters)} cross-file duplicate cluster(s) ===")
        for part_a, claim_a, part_b, claim_b in clusters:
            total_clusters += 1
            print(f"  [{claim_a.get('domain')}]")
            print(
                f"    {part_a}: {claim_a.get('claim_key')!r} "
                f"({claim_a.get('status')}, {len(claim_a.get('sources') or [])} src) — {claim_a.get('title')!r}"
            )
            print(
                f"    {part_b}: {claim_b.get('claim_key')!r} "
                f"({claim_b.get('status')}, {len(claim_b.get('sources') or [])} src) — {claim_b.get('title')!r}"
            )

    print(f"\nTOTAL: {total_clusters} cross-file duplicate cluster(s) found across all models.")
    print("Report-only — no files modified. Decide a merge policy before writing a fixer.")


if __name__ == "__main__":
    main()
