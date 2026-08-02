"""20+ real Sahibinden listing shapes for Renault Megane IV.

Each listing dict mirrors exactly what content.js produces and
background.js sends as ad_metadata in the /analyze payload.
"""

import pytest
from backend.core.matcher import match_variant


# ── Happy-path exact matches ──────────────────────────────────────────────────

def test_k9k_110_diesel_exact(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2019,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
        "transmission": "Manuel",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_k9k_110"]


def test_k9k_90_diesel_exact(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2017,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 90,
        "transmission": "Manuel",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_k9k_90"]


def test_h5h_140_petrol_exact(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "Benzin", "engine_volume_cc": 1332, "power_hp": 140,
        "transmission": "Otomatik",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_h5h_140"]


def test_h5h_115_petrol_exact(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2021,
        "fuel_type": "Benzin", "engine_volume_cc": 1332, "power_hp": 115,
        "transmission": "Otomatik",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_h5h_115"]


def test_h5f_100_petrol_exact(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2017,
        "fuel_type": "Benzin", "engine_volume_cc": 1197, "power_hp": 100,
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_h5f_100"]


def test_h5f_130_petrol_exact(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2018,
        "fuel_type": "Benzin", "engine_volume_cc": 1197, "power_hp": 130,
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_h5f_130"]


def test_r9m_130_diesel_auto(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2019,
        "fuel_type": "Dizel", "engine_volume_cc": 1598, "power_hp": 130,
        "transmission": "Otomatik",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_r9m_130"]


# ── Sahibinden quirks — Turkish field names and alternate spellings ───────────

def test_fuel_type_uppercase_dizel(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "DIZEL", "engine_volume_cc": 1461, "power_hp": 110,
    }
    # normalize_fuel lowercases, so DIZEL → diesel. No transmission stated, so
    # both the manual k9k_110 and the automatic k9k_110_edc survive (B3).
    r = match_variant(meta, db)
    assert r.method == "ambiguous"
    assert set(r.variant_ids) == {"megane4_k9k_110", "megane4_k9k_110_edc"}


def test_fuel_type_lpg_matches_as_petrol(db, megane4_variants):
    # LPG-converted petrol cars often appear as "LPG" in Sahibinden.
    # Normalize maps LPG → petrol so we match the base petrol variant.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2018,
        "fuel_type": "LPG & Benzin", "engine_volume_cc": 1332, "power_hp": 115,
    }
    r = match_variant(meta, db)
    # H5H 115 is petrol; LPG-converted maps to petrol. Year 2018 is on the
    # boundary; H5H starts 2018 and H5F ends 2018.
    assert r.method in ("exact", "ambiguous")


def test_transmission_edc_normalizes_to_automatic(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2021,
        "fuel_type": "Benzin", "engine_volume_cc": 1332, "power_hp": 140,
        "transmission": "EDC",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_h5h_140"]


def test_turkish_accent_megane_model(db, megane4_variants):
    # "Mégane" with accent — normalize_model handles this
    meta = {
        "make": "Renault", "model": "Mégane", "year": 2020,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
    }
    r = match_variant(meta, db)
    assert r.method == "ambiguous"
    assert set(r.variant_ids) == {"megane4_k9k_110", "megane4_k9k_110_edc"}


# ── Ambiguous listings — missing or unresolvable power data ──────────────────

def test_k9k_ambiguous_no_power(db, megane4_variants):
    # K9K diesel manual variants are 90hp and 110hp (1461cc); the automatic
    # EDC row (B3) is also 110hp 1461cc. Without power data all three survive —
    # should be ambiguous.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2019,
        "fuel_type": "Dizel", "engine_volume_cc": 1461,
        # power_hp intentionally missing
    }
    r = match_variant(meta, db)
    assert r.method == "ambiguous"
    assert set(r.variant_ids) == {"megane4_k9k_90", "megane4_k9k_110", "megane4_k9k_110_edc"}


def test_h5h_ambiguous_no_power(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2022,
        "fuel_type": "Benzin", "engine_volume_cc": 1332,
    }
    r = match_variant(meta, db)
    assert r.method == "ambiguous"
    assert set(r.variant_ids) == {"megane4_h5h_115", "megane4_h5h_140"}


def test_h5h_ambiguous_no_cc_no_power(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "Benzin",
    }
    r = match_variant(meta, db)
    assert r.method == "ambiguous"
    # H5F ended 2018; H5H started 2018. For 2020 only H5H variants are active.
    assert set(r.variant_ids) == {"megane4_h5h_115", "megane4_h5h_140"}


# ── No-match cases ────────────────────────────────────────────────────────────

def test_no_match_wrong_year(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2010,
        "fuel_type": "Dizel", "engine_volume_cc": 1461,
    }
    r = match_variant(meta, db)
    assert r.method == "no_match"
    assert r.variant_ids == []


def test_no_match_different_make(db, megane4_variants):
    meta = {
        "make": "Peugeot", "model": "Megane", "year": 2020,
        "fuel_type": "Dizel",
    }
    r = match_variant(meta, db)
    assert r.method == "no_match"


def test_no_match_unknown_model(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Trafic", "year": 2020,
        "fuel_type": "Dizel",
    }
    r = match_variant(meta, db)
    assert r.method == "no_match"


def test_no_match_missing_make(db, megane4_variants):
    meta = {"model": "Megane", "year": 2020, "fuel_type": "Dizel"}
    r = match_variant(meta, db)
    assert r.method == "no_match"


def test_no_match_missing_fuel(db, megane4_variants):
    meta = {"make": "Renault", "model": "Megane", "year": 2020}
    r = match_variant(meta, db)
    assert r.method == "no_match"


def test_no_match_missing_year(db, megane4_variants):
    meta = {"make": "Renault", "model": "Megane", "fuel_type": "Dizel"}
    r = match_variant(meta, db)
    assert r.method == "no_match"


# ── Inconsistent listing ──────────────────────────────────────────────────────

def test_inconsistent_cc_diesel_engine_in_petrol_body(db, megane4_variants):
    # A listing that says it's a diesel Megane but cc = 1332 (H5H petrol cc).
    # No diesel variant has 1332cc — should be flagged as inconsistent.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2021,
        "fuel_type": "Dizel", "engine_volume_cc": 1332, "power_hp": 140,
    }
    r = match_variant(meta, db)
    assert r.method == "inconsistent_listing"
    assert r.variant_ids == []


def test_inconsistent_cc_implausibly_large(db, megane4_variants):
    # cc=9000 is outside any car's range — _safe_cc returns None, so we
    # fall through to ambiguous (no cc filter applied), not inconsistent.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "Benzin", "engine_volume_cc": 9000,
    }
    r = match_variant(meta, db)
    # cc is sanitised away, so matcher treats it as no cc provided
    assert r.method == "ambiguous"


def test_garbage_power_from_content_js(db, megane4_variants):
    # content.js produces "96130" from "96 kW / 130 hp" → numberFromText.
    # _safe_hp rejects values > 600; matcher treats hp as missing.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2019,
        "fuel_type": "Benzin", "engine_volume_cc": 1332, "power_hp": 96130,
    }
    r = match_variant(meta, db)
    # power sanitised away → H5H variants both survive → ambiguous
    assert r.method == "ambiguous"
    assert set(r.variant_ids) == {"megane4_h5h_115", "megane4_h5h_140"}


# ── Boundary year tests ───────────────────────────────────────────────────────

def test_h5f_last_year_2018(db, megane4_variants):
    # H5F ended 2018, H5H started 2018 — both active in 2018 for their power ranges.
    # 1197cc uniquely identifies H5F.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2018,
        "fuel_type": "Benzin", "engine_volume_cc": 1197, "power_hp": 130,
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_h5f_130"]


def test_h5h_first_year_2018(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2018,
        "fuel_type": "Benzin", "engine_volume_cc": 1332, "power_hp": 140,
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_h5h_140"]


def test_k9k_present_through_2023(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2023,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 90,
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_k9k_90"]


def test_h5f_not_present_2019(db, megane4_variants):
    # H5F ended 2018. A 2019 listing claiming 1197cc petrol is inconsistent.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2019,
        "fuel_type": "Benzin", "engine_volume_cc": 1197, "power_hp": 130,
    }
    r = match_variant(meta, db)
    # No petrol Megane variant with 1197cc after 2018 → no_match or inconsistent
    assert r.method in ("no_match", "inconsistent_listing")


# ── Transmission soft-filter ──────────────────────────────────────────────────

def test_wrong_transmission_caught_by_edc_row(db, megane4_variants):
    # B3: the automatic 1.5 dCi EDC Megane used to silently "exact"-match the
    # manual k9k_110 row (soft tx filter fallback) with no gearbox risks at all.
    # The k9k_110_edc row now catches the automatic ad instead.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
        "transmission": "Otomatik",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_k9k_110_edc"]
    assert r.tx_mismatch is False


def test_missing_transmission_does_not_block(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
    }
    r = match_variant(meta, db)
    assert r.method == "ambiguous"
    assert set(r.variant_ids) == {"megane4_k9k_110", "megane4_k9k_110_edc"}
