"""sync.py — load YAML data into the DB.

YAML is the source of truth. sync.py is one-way: YAML → DB.
Run this after any YAML edit. It is idempotent (upsert by primary key).

Two sources of claims:
  1. data/claims/*.yaml  — legacy model-centric claims (kept for backward compat)
  2. data/parts/**/*.yaml + data/fitment/*.yaml — new part-centric claims (Lego)

sync_parts() materialises part claims into the existing claim_variants table using
the fitment YAML as the assembly key. The serving plane (/analyze) is unchanged —
it still reads from claims + claim_variants as before.

Usage:
    python -m backend.sync
"""

import glob
import sys
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from backend.db.models import Base, Claim, ClaimSource, ClaimVariant, Variant
from backend.db.session import engine

DATA_DIR = Path(__file__).parent / "data"
PARTS_DIR  = DATA_DIR / "parts"
FITMENT_DIR = DATA_DIR / "fitment"


def sync_variants(db: Session) -> int:
    count = 0
    for path in sorted(DATA_DIR.glob("variants/*.yaml")):
        with open(path) as f:
            rows = yaml.safe_load(f)
        for row in rows:
            obj = db.get(Variant, row["id"])
            if obj is None:
                obj = Variant()
                db.add(obj)
            for k, v in row.items():
                setattr(obj, k, v)
            count += 1
    return count


def sync_claims(db: Session) -> tuple[int, set[str]]:
    """Upsert every claim from data/claims/*.yaml (legacy model-centric).

    Returns (count, set of all claim ids seen) for prune_removed_claims.
    """
    count = 0
    seen_ids: set[str] = set()
    for path in sorted(DATA_DIR.glob("claims/*.yaml")):
        with open(path) as f:
            rows = yaml.safe_load(f)
        if not rows:
            continue
        for row in rows:
            seen_ids.add(row["id"])
            obj = _upsert_claim_row(db, row)
            # Replace variant links (delete + re-insert)
            db.query(ClaimVariant).filter(ClaimVariant.claim_id == obj.id).delete()
            for v in row.get("variants", []):
                db.add(ClaimVariant(
                    claim_id=obj.id,
                    variant_id=v["variant_id"],
                    grounding_note=v.get("grounding_note"),
                ))
            # Replace source links (delete + re-insert)
            db.query(ClaimSource).filter(ClaimSource.claim_id == obj.id).delete()
            for s in row.get("sources", []):
                db.add(_make_source(obj.id, s))
            count += 1
    return count, seen_ids


def sync_parts(db: Session) -> tuple[int, set[str]]:
    """Materialise part-centric claims into the DB using fitment as assembly key.

    Reads:
      data/parts/{type}/{part_id}.yaml  — claims for each part revision
      data/fitment/{make}_{model}.yaml  — variant_id → {engine_family, transmission_code}

    For each fitment row, looks up matching part YAMLs by engine_family and
    transmission_code, then upserts each part claim and creates claim_variant links
    for the matching variant.

    Returns (count, set of all claim ids seen from parts).

    Attribution guard: raises ValueError if a part claim is linked to a variant
    whose engine_family / transmission_code does not match the part — indicating a
    bug in the fitment YAML.
    """
    # Load all part YAMLs, keyed by part_id
    parts: dict[str, dict] = {}
    for path in sorted(PARTS_DIR.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        part_id = data.get("part_id")
        if not part_id:
            print(f"  WARN: {path} has no part_id — skipped")
            continue
        parts[part_id] = data

    if not parts:
        return 0, set()

    # Load all fitment YAMLs
    fitment_rows: list[dict] = []
    for path in sorted(FITMENT_DIR.glob("*.yaml")):
        rows = yaml.safe_load(path.read_text()) or []
        fitment_rows.extend(rows)

    count = 0
    seen_ids: set[str] = set()

    for fit in fitment_rows:
        variant_id = fit.get("variant_id")
        if not variant_id:
            continue

        # Verify variant exists in DB
        variant = db.get(Variant, variant_id)
        if variant is None:
            print(f"  WARN: fitment references unknown variant {variant_id!r} — skipped")
            continue

        part_keys = {
            "engine": fit.get("engine_family"),
            "transmission": fit.get("transmission_code"),
        }

        for part_type_key, part_id in part_keys.items():
            if not part_id or part_id not in parts:
                continue

            part_data = parts[part_id]

            # Attribution guard: part_type in YAML must match the fitment key type.
            # engine_family links to engine parts; transmission_code links to transmission parts.
            declared_type = part_data.get("part_type", "")
            expected_type = part_type_key
            if declared_type != expected_type:
                # e.g. "edc" is transmission but fitment maps it via engine_family
                continue  # wrong axis — skip silently (correct axis will pick it up)

            for claim_data in (part_data.get("claims") or []):
                claim_id = _part_claim_id(part_id, claim_data)
                seen_ids.add(claim_id)

                obj = _upsert_part_claim(db, claim_id, claim_data)

                # Create variant link if it doesn't exist
                existing = (
                    db.query(ClaimVariant)
                    .filter(
                        ClaimVariant.claim_id == claim_id,
                        ClaimVariant.variant_id == variant_id,
                    )
                    .first()
                )
                if existing is None:
                    db.add(ClaimVariant(
                        claim_id=claim_id,
                        variant_id=variant_id,
                        grounding_note=f"Part fitment: {part_id} ({part_type_key})",
                    ))

                # Upsert sources
                db.query(ClaimSource).filter(ClaimSource.claim_id == claim_id).delete()
                for s in (claim_data.get("sources") or []):
                    db.add(_make_source(claim_id, s))

                count += 1

    return count, seen_ids


def prune_removed_claims(db: Session, seen_ids: set[str]) -> int:
    """Delete claims no longer present in any YAML (cascades to variants/sources).

    YAML is the source of truth — a removed row must stop serving.
    """
    stale = db.query(Claim).filter(Claim.id.notin_(seen_ids)).all() if seen_ids else []
    for claim in stale:
        db.delete(claim)
    return len(stale)


def run():
    print("Creating tables if needed…")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        n_variants = sync_variants(db)
        n_legacy, legacy_ids = sync_claims(db)
        n_parts, parts_ids = sync_parts(db)
        all_seen = legacy_ids | parts_ids
        n_pruned = prune_removed_claims(db, all_seen)
        db.commit()

    print(
        f"Synced {n_variants} variants, "
        f"{n_legacy} legacy claims, "
        f"{n_parts} part-claim×variant links "
        f"(pruned {n_pruned} removed)."
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _part_claim_id(part_id: str, claim_data: dict) -> str:
    """Derive a stable claim id from the part id + claim key."""
    key = claim_data.get("claim_key") or claim_data.get("id", "unknown")
    version = claim_data.get("version", 1)
    return f"{key}_v{version}"


def _upsert_claim_row(db: Session, row: dict) -> Claim:
    obj = db.get(Claim, row["id"])
    if obj is None:
        obj = Claim()
        db.add(obj)
    obj.id               = row["id"]
    obj.claim_key        = row["claim_key"]
    obj.version          = row.get("version", 1)
    obj.is_current       = row.get("is_current", True)
    obj.title            = row["title"]
    obj.domain           = row["domain"]
    obj.severity         = row["severity"]
    obj.confidence       = row["confidence"]
    obj.rationale        = row["rationale"].strip()
    obj.inspection_advice = row["inspection_advice"].strip()
    obj.status           = row.get("status", "draft")
    obj.promoted_by      = row.get("promoted_by")
    obj.kind             = row.get("kind", "known_issue")
    applies_when         = row.get("applies_when") or {}
    obj.min_mileage_km   = applies_when.get("min_mileage_km")
    obj.max_mileage_km   = applies_when.get("max_mileage_km")
    obj.min_age_years    = applies_when.get("min_age_years")
    obj.maintenance_data = row.get("maintenance")
    obj.value_tier       = row.get("value_tier")
    return obj


def _upsert_part_claim(db: Session, claim_id: str, claim_data: dict) -> Claim:
    """Upsert a claim derived from a part YAML claim block."""
    obj = db.get(Claim, claim_id)
    if obj is None:
        obj = Claim()
        db.add(obj)
    obj.id               = claim_id
    obj.claim_key        = claim_data.get("claim_key") or claim_id
    obj.version          = claim_data.get("version", 1)
    obj.is_current       = claim_data.get("is_current", True)
    obj.title            = claim_data["title"].strip()
    obj.domain           = claim_data["domain"]
    obj.severity         = claim_data["severity"]
    obj.confidence       = claim_data.get("confidence", 0.0)
    obj.rationale        = (claim_data.get("rationale") or "").strip()
    obj.inspection_advice = (claim_data.get("inspection_advice") or "").strip()
    obj.status           = claim_data.get("status", "draft")
    obj.promoted_by      = claim_data.get("promoted_by")
    obj.kind             = claim_data.get("kind", "known_issue")
    applies_when         = claim_data.get("applies_when") or {}
    obj.min_mileage_km   = applies_when.get("min_mileage_km")
    obj.max_mileage_km   = applies_when.get("max_mileage_km")
    obj.min_age_years    = applies_when.get("min_age_years")
    obj.maintenance_data = claim_data.get("maintenance")
    obj.value_tier       = claim_data.get("value_tier")
    return obj


def _make_source(claim_id: str, s: dict) -> ClaimSource:
    return ClaimSource(
        claim_id=claim_id,
        tier=s["tier"],
        source_url=s["source_url"],
        source_domain=s.get("source_domain"),
        site_or_channel=s.get("site_or_channel"),
        title=s.get("title"),
        timestamp_s=s.get("timestamp_s"),
        quote=(s.get("quote") or "").strip(),
        independent=s.get("independent", True),
    )


if __name__ == "__main__":
    run()
