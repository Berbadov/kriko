"""One-off generator for backend/tests/fixtures/serving_gold/*.json.

Runs the real pipeline (sync → match_variant → resolve_claims) over five
real-world listing shapes and records the served claim_keys as the gold set.
Run from the repo root:

    .venv/bin/python backend/tests/fixtures/serving_gold/generate.py

Re-generate ONLY when a deliberate serving-behaviour change is intended —
the point of the gold set is to fail when serving changes by accident.
"""

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.core.context import ListingContext  # noqa: E402
from backend.core.matcher import match_variant  # noqa: E402
from backend.core.recover import recover_listing_fields  # noqa: E402
from backend.core.resolver import resolve_claims  # noqa: E402
from backend.db.models import Base, Claim, ClaimSource, ClaimVariant, Variant  # noqa: E402
from backend.sync import sync_claims, sync_parts, sync_variants  # noqa: E402
from datetime import date  # noqa: E402

LISTINGS = [
    {
        "name": "golf7_1_6_tdi_dsg_high_km",
        "ad_metadata": {
            "make": "Volkswagen", "model": "Golf", "year": 2018,
            "fuel_type": "Dizel", "transmission": "Otomatik",
            "engine_volume_cc": 1598, "power_hp": 105,
            "mileage_km": 287000,
            "url": "https://www.sahibinden.com/ilan/vasita-araba/volkswagen-golf-1.6-tdi-dsg",
        },
    },
    {
        "name": "megane4_1_5_dci_manual_low_km",
        "ad_metadata": {
            "make": "Renault", "model": "Megane", "year": 2019,
            "fuel_type": "Dizel", "transmission": "Manuel",
            "engine_volume_cc": 1461, "power_hp": 90,
            "mileage_km": 46500,
            "url": "https://www.sahibinden.com/ilan/vasita-araba/renault-megane-1.5-dci-joy",
        },
    },
    {
        "name": "clio5_1_0_tce_petrol",
        "ad_metadata": {
            "make": "Renault", "model": "Clio", "year": 2020,
            "fuel_type": "Benzinli", "transmission": "Manuel",
            "engine_volume_cc": 999, "power_hp": 100,
            "mileage_km": 84000,
            "url": "https://www.sahibinden.com/ilan/vasita-araba/renault-clio-1.0-tce",
        },
    },
    {
        "name": "golf7_gti_2_0_tsi_dsg",
        "ad_metadata": {
            "make": "Volkswagen", "model": "Golf", "year": 2018,
            "fuel_type": "Benzinli", "transmission": "DSG",
            "engine_volume_cc": 1984, "power_hp": 230,
            "mileage_km": 165000,
            "url": "https://www.sahibinden.com/ilan/vasita-araba/volkswagen-golf-gti",
        },
    },
    {
        "name": "megane4_1_5_dci_edc_high_km",
        "ad_metadata": {
            "make": "Renault", "model": "Megane", "year": 2018,
            "fuel_type": "Dizel", "transmission": "Otomatik",
            "engine_volume_cc": 1461, "power_hp": 110,
            "mileage_km": 243000,
            "url": "https://www.sahibinden.com/ilan/vasita-araba/renault-megane-1.5-dci-edc",
        },
    },
]


def build_db() -> Session:
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in [Variant.__table__, Claim.__table__, ClaimVariant.__table__, ClaimSource.__table__]:
        table.create(eng, checkfirst=True)
    db = Session(eng)
    sync_variants(db)
    sync_claims(db)
    sync_parts(db)
    db.flush()
    return db


def main() -> None:
    db = build_db()
    for listing in LISTINGS:
        meta = recover_listing_fields(dict(listing["ad_metadata"]))
        ctx = ListingContext(
            mileage_km=meta.get("mileage_km"),
            age_years=(date.today().year - meta["year"]) if meta.get("year") else None,
            model_year=meta.get("year"),
            fuel_type=meta.get("fuel_type"),
            transmission=meta.get("transmission"),
        )
        match = match_variant(meta, db)
        served = resolve_claims(match, db, ctx)
        claim_keys = sorted({cr.claim.claim_key for cr in served})
        fixture = {
            "name": listing["name"],
            "description": listing["name"].replace("_", " "),
            "ad_metadata": listing["ad_metadata"],
            "expected_matched_variant_ids": sorted(match.variant_ids),
            "expected_claim_keys": claim_keys,
        }
        out = Path(__file__).parent / f"{listing['name']}.json"
        out.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{listing['name']}: variants={match.variant_ids} claims={len(claim_keys)}")


if __name__ == "__main__":
    main()
