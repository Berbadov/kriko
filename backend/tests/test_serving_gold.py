"""Serving gold set — real-world listing payloads replayed end-to-end.

Each fixture in backend/tests/fixtures/serving_gold/*.json is a real-world
listing shape (the DOM scrape's ad_metadata) plus the claim_keys the serving
plane is expected to produce for it. The test builds a fully synced test DB
(sync_variants + sync_claims + sync_parts against the real YAML — the same
one-way load production runs) and replays every payload through
match_variant + resolve_claims.

This is the regression harness docs/design_flaws.md asks for: any pipeline
change that silently alters what buyers see fails here, not in production.
Regenerate the fixtures only for deliberate serving-behaviour changes
(see generate.py in the same directory).
"""

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.core.context import ListingContext
from backend.core.matcher import match_variant
from backend.core.recover import recover_listing_fields
from backend.core.resolver import resolve_claims
from backend.db.models import Claim, ClaimSource, ClaimVariant, Variant
from backend.sync import sync_claims, sync_parts, sync_variants

GOLD_DIR = Path(__file__).parent / "fixtures" / "serving_gold"
FIXTURES = sorted(GOLD_DIR.glob("*.json"))


@pytest.fixture(scope="module")
def gold_db():
    """A DB synced exactly like production: every variant/claim/fitment YAML
    under backend/data, loaded once for the whole module (the sync is not
    cheap; the replay itself is pure reads)."""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in [Variant.__table__, Claim.__table__, ClaimVariant.__table__, ClaimSource.__table__]:
        table.create(eng, checkfirst=True)
    db = Session(eng)
    sync_variants(db)
    sync_claims(db)
    sync_parts(db)
    db.flush()
    yield db
    db.rollback()
    eng.dispose()


def _replay(meta: dict, db: Session):
    """Same context construction as api.run_analysis (recover → ctx → match →
    resolve), so the gold set exercises the real serve path, not a copy."""
    meta = recover_listing_fields(dict(meta))
    ctx = ListingContext(
        mileage_km=meta.get("mileage_km"),
        age_years=(date.today().year - meta["year"]) if meta.get("year") else None,
        model_year=meta.get("year"),
        fuel_type=meta.get("fuel_type"),
        transmission=meta.get("transmission"),
        description=(meta.get("description") or "").lower(),
        equipment=meta.get("equipment") or None,
    )
    match = match_variant(meta, db)
    served = resolve_claims(match, db, ctx)
    return match, served


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=lambda p: p.stem)
def test_gold_serving(fixture_path, gold_db):
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    match, served = _replay(data["ad_metadata"], gold_db)

    assert sorted(match.variant_ids) == data["expected_matched_variant_ids"], (
        f"{fixture_path.name}: matched variants drifted — "
        f"got {sorted(match.variant_ids)}"
    )

    got = sorted({cr.claim.claim_key for cr in served})
    expected = sorted(set(data["expected_claim_keys"]))
    missing = [k for k in expected if k not in got]
    extra = [k for k in got if k not in expected]
    assert got == expected, (
        f"{fixture_path.name}: served claim set drifted — "
        f"missing {missing}, unexpected {extra}. "
        "If this change is intentional, regenerate the gold set "
        "(backend/tests/fixtures/serving_gold/generate.py)."
    )


def test_gold_covers_the_five_real_world_shapes():
    """Guard the guard: the gold set must keep covering the five listing
    shapes it was built for, so a deleted fixture can't silently shrink
    coverage."""
    names = {p.stem for p in FIXTURES}
    assert {
        "golf7_1_6_tdi_dsg_high_km",
        "megane4_1_5_dci_manual_low_km",
        "clio5_1_0_tce_petrol",
        "golf7_gti_2_0_tsi_dsg",
        "megane4_1_5_dci_edc_high_km",
    } <= names
