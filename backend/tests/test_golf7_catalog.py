"""Golf 7 variant coverage, matched against the real catalog YAML.

Live gap (2026-07-13): a real listing — 2016 Golf 1.2 TSI Comfortline DSG,
1197 cc / 110 hp — scraped perfectly but matched nothing, because the catalog
carried only the 1.0 TSI (998 cc), 1.4 TSI (1395 cc) and 2.0. The matcher
correctly refused to guess rather than serve another engine's risks; the fix is
catalog coverage, not matcher leniency.

These run against backend/data/variants/volkswagen_golf_7.yaml itself, so a
regenerated catalog that drops or renames the variant fails here.
"""

import yaml
import pytest
from pathlib import Path

from backend.core.matcher import match_variant
from backend.db.models import Variant

VARIANTS_YAML = (
    Path(__file__).parent.parent / "data" / "variants" / "volkswagen_golf_7.yaml"
)


@pytest.fixture
def golf7_variants(db):
    rows = yaml.safe_load(VARIANTS_YAML.read_text())
    valid = {c.name for c in Variant.__table__.columns}
    for row in rows:
        db.add(Variant(**{k: v for k, v in row.items() if k in valid}))
    db.flush()
    return rows


def _listing(**over):
    """The user's real listing, as the scraper now reads it from the page."""
    meta = {
        "make": "Volkswagen", "model": "Golf", "year": 2016,
        "fuel_type": "Gasoline", "transmission": "DSG",
        "engine_volume_cc": 1197, "power_hp": 110, "mileage_km": 132000,
    }
    meta.update(over)
    return meta


def test_golf_1_2_tsi_dsg_matches_a_variant(db, golf7_variants):
    match = match_variant(_listing(), db)
    assert match.variant_ids, f"1.2 TSI DSG matched nothing: {match.notes}"
    assert match.variant_ids == ["golf7_ea211_110_dsg"]


def test_golf_1_2_tsi_manual_matches_the_manual_variant(db, golf7_variants):
    match = match_variant(_listing(transmission="Manuel"), db)
    assert match.variant_ids == ["golf7_ea211_110"]


def test_the_1_2_tsi_is_an_ea211_so_it_inherits_that_engine_family(golf7_variants):
    rows = {r["id"]: r for r in golf7_variants}
    assert rows["golf7_ea211_110_dsg"]["engine_family"] == "ea211"
    # ...and the DSG is the DQ200 already onboarded for the 1.4 TSI DSG.
    assert rows["golf7_ea211_110_dsg"]["transmission_code"] == "dq200"


def test_the_1_0_tsi_is_not_confused_with_the_1_2(db, golf7_variants):
    # Both are EA211 at 105 hp; only displacement separates them. A 998 cc
    # listing must not match the 1197 cc variant. Year 2018: the 1.0 TSI is a
    # facelift engine (2017+) and replaced the 1.2 TSI, so the two barely overlap.
    match = match_variant(_listing(year=2018, engine_volume_cc=998, power_hp=105,
                                   transmission="Manuel"), db)
    assert match.variant_ids == ["golf7_ea211_105"]
