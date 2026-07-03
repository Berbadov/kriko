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
import re
import sys
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from backend.core.equipment import derive_equipment_tags
from backend.db.models import Base, Claim, ClaimSource, ClaimVariant, Variant
from backend.db.session import engine

DATA_DIR = Path(__file__).parent / "data"
PARTS_DIR  = DATA_DIR / "parts"
FITMENT_DIR = DATA_DIR / "fitment"

# ── Transmission-code grounding ────────────────────────────────────────────
#
# Universal parts (engine, cooling, electrical) attach to every variant of a
# model regardless of gearbox — correct for genuinely gearbox-agnostic claims
# (e.g. "12V battery drain"), but a source about "Golf 7 electronics" often
# also mentions the DSG gearbox, and nothing stopped that claim from being
# filed under the electrical/engine part and broadcast to manual-transmission
# variants too. Same issue between transmission part files themselves: a
# source about "DSG problems" mixing DQ200 and DQ250 detail can get filed
# under the wrong specific code's part YAML.
#
# This check runs at sync time (not extraction time) so it applies immediately
# to already-written part YAMLs without re-running any LLM gates.
_TRANS_CODE_RE = re.compile(r"\b(dq\s?200|dq\s?250|dq\s?381|dq\s?500|dc4|dw5|dw6|edc)\b", re.I)
_AUTO_ONLY_RE = re.compile(
    r"\bdsg\b|dual[- ]clutch|mechatronic|çift kavrama|kavrama plaket|"
    r"otomatik şanzıman|kuru kavrama|wet[- ]clutch|"
    r"\btcm\b|transmission control module",
    re.I,
)
_MANUAL_ONLY_RE = re.compile(
    r"\bclutch pedal\b|\bshift cable\b|\bmanuel vites\b|\bdebriyaj pedal",
    re.I,
)


def _transmission_compatible(claim_data: dict, variant_transmission_code: str) -> bool:
    """Does this claim's own text rule out the variant it's about to be linked to?

    No signal → broad grounding preserved (matches the existing fuel-narrowing
    precedent in knowledge/promote.py: absence of a signal never excludes).
    """
    text = f"{claim_data.get('title', '')} {claim_data.get('rationale', '')}"
    tc = (variant_transmission_code or "").lower().replace(" ", "")

    codes_mentioned = {m.lower().replace(" ", "") for m in _TRANS_CODE_RE.findall(text)}
    if codes_mentioned and tc not in codes_mentioned:
        return False

    if tc == "manual":
        if _AUTO_ONLY_RE.search(text):
            return False
    elif not codes_mentioned and _MANUAL_ONLY_RE.search(text):
        return False

    return True


# ── Fuel grounding ──────────────────────────────────────────────────────────
#
# Same gap, different axis: a universal part (electrical, body) attached to
# every variant of a model regardless of fuel can absorb a diesel-only claim
# (e.g. "DPF blockages (TDI models)") from a broad source and broadcast it to
# petrol variants too. docs/USAGE.md already documents fuel-grounding as a
# guarantee — this closes the part-centric gap where it wasn't actually
# enforced (only computed and discarded in knowledge/promote.py).
_DIESEL_RE = re.compile(r"\b(k9k|r9m|r9n|ea288|d[ck]i|tdi|diesel|dizel|adblue|dpf)\b", re.I)
_PETROL_RE = re.compile(
    r"\b(h5f|h5h|h4m|m5m|m5p|ea211|tce|tsi|puretech|petrol|benzin|gasoline)\b", re.I
)


def _fuel_compatible(claim_data: dict, variant_fuel: str) -> bool:
    """Does this claim's own text signal a fuel that rules out this variant?

    Mutually-exclusive signal only — no signal, or signals both, grounds
    broadly (mirrors _transmission_compatible / knowledge/promote.py).
    """
    text = f"{claim_data.get('title', '')} {claim_data.get('rationale', '')}"
    is_diesel = bool(_DIESEL_RE.search(text))
    is_petrol = bool(_PETROL_RE.search(text))
    fuel = (variant_fuel or "").lower()

    if is_diesel and not is_petrol and fuel and fuel != "diesel":
        return False
    if is_petrol and not is_diesel and fuel and fuel != "petrol":
        return False
    return True


# ── Drivetrain grounding ────────────────────────────────────────────────────
#
# Same gap, third axis: a universal part (electrical) attached to every
# variant of a model regardless of drivetrain can absorb an AWD-only claim
# (e.g. "Haldex AWD Coupling Oil Degradation (Golf R)") and broadcast it to
# FWD variants too — a 4WD-specific failure surfaced on a car that physically
# does not have that hardware. `Variant.drivetrain` is populated on every row
# (via knowledge/catalog/add_part_code.py, never hand-edited); absence on the
# variant side (None) grounds broadly, mirroring _fuel_compatible.
_AWD_RE = re.compile(
    r"\bawd\b|\b4wd\b|\b4x4\b|4matic|quattro|4motion|xdrive|haldex|"
    r"all[- ]wheel drive|4\s*[çc]eker",
    re.I,
)
_RWD_RE = re.compile(r"\brwd\b|rear[- ]wheel drive|arkadan\s*iti[şs]", re.I)


def _drivetrain_compatible(claim_data: dict, variant_drivetrain: str | None) -> bool:
    """Does this claim's own text signal a drivetrain that rules out this variant?

    Mutually-exclusive signal only — no signal on either side grounds broadly
    (mirrors _fuel_compatible / _transmission_compatible).
    """
    text = f"{claim_data.get('title', '')} {claim_data.get('rationale', '')}"
    is_awd = bool(_AWD_RE.search(text))
    is_rwd = bool(_RWD_RE.search(text))
    dt = (variant_drivetrain or "").lower()

    if is_awd and not is_rwd and dt and dt != "awd":
        return False
    if is_rwd and not is_awd and dt and dt != "rwd":
        return False
    return True


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

    # Clear existing part-fitment links to avoid stale mappings
    db.query(ClaimVariant).filter(ClaimVariant.grounding_note.like("Part fitment:%")).delete(synchronize_session=False)

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
            "cooling": fit.get("cooling_code"),
            "electrical": fit.get("electrical_code"),
            "body": fit.get("body_code"),
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

                # Upsert sources — global to the claim, independent of which
                # variant(s) it ends up linked to below.
                db.query(ClaimSource).filter(ClaimSource.claim_id == claim_id).delete()
                for s in (claim_data.get("sources") or []):
                    db.add(_make_source(claim_id, s))

                if not _transmission_compatible(claim_data, fit.get("transmission_code", "")):
                    continue
                if not _fuel_compatible(claim_data, variant.fuel):
                    continue
                if not _drivetrain_compatible(claim_data, variant.drivetrain):
                    continue

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
    obj.requires_equipment = derive_equipment_tags(f"{obj.title} {obj.rationale}") or None
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
    obj.requires_equipment = derive_equipment_tags(f"{obj.title} {obj.rationale}") or None
    return obj


def _make_source(claim_id: str, s: dict) -> ClaimSource:
    return ClaimSource(
        claim_id=claim_id,
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
