"""Ad-vs-catalog transmission contradiction surfacing (backlog B6).

matcher.py's `_narrow_by_transmission` is a *soft* filter: when the ad states a
transmission that no candidate variant is cataloged with, it silently falls back
to the unnarrowed set. The match still succeeds on the (engine-correct) variant,
but the buyer gets no signal that its cataloged gearbox differs from the ad's —
so gearbox-specific risks are silently absent. Production case (2026-07-13): an
EDC/automatic Megane 1.5 dCi "exact"-matched `megane4_k9k_110`, cataloged
`transmission: manual`, with zero gearbox claims and no caveat.

These tests pin: the match is unchanged, but `MatchResult.tx_mismatch` is set and
a stable `tx_coverage_gap:` note is appended (which is also the catalog-gap
mining signal in the analysis logs), and the /analyze summary carries a
buyer-visible caveat.
"""

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.api.main import TX_MISMATCH_CAVEAT, app
from backend.core.matcher import match_variant
from backend.db.models import Variant
from backend.db.session import get_db


# ── matcher-level detection ───────────────────────────────────────────────────

def test_automatic_ad_on_manual_only_engine_flags_gap(db, megane4_variants):
    # K9K 1.5 dCi is cataloged manual-only; the ad reports an automatic. The
    # match still lands on k9k_110 (engine claims are valid) but the contradiction
    # must be recorded.
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
        "transmission": "Otomatik",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_k9k_110"]
    assert r.tx_mismatch is True
    assert "tx_coverage_gap:" in r.notes
    # The note names both sides of the contradiction for the log-mining signal.
    assert "automatic" in r.notes
    assert "manual" in r.notes


def test_matching_transmission_is_not_flagged(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
        "transmission": "Manuel",
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.variant_ids == ["megane4_k9k_110"]
    assert r.tx_mismatch is False
    assert "tx_coverage_gap:" not in r.notes


def test_missing_transmission_is_not_flagged(db, megane4_variants):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
    }
    r = match_variant(meta, db)
    assert r.method == "exact"
    assert r.tx_mismatch is False
    assert "tx_coverage_gap:" not in r.notes


def _add_variant(db, id_, tx):
    db.add(Variant(
        id=id_, make="testmake", model="testmodel", fuel="petrol",
        displacement_cc=2000, power_min_hp=100, power_max_hp=200,
        transmission=tx, year_from=2015, year_to=2025, market="TR",
    ))
    db.flush()


def test_ambiguous_with_a_matching_candidate_is_not_flagged(db):
    # Mixed candidate set (two automatic, one manual). Ad reports automatic:
    # the soft filter *succeeds* (drops the manual), so the surviving ambiguous
    # set all match the ad's transmission — no contradiction, no flag.
    _add_variant(db, "auto_a", "automatic")
    _add_variant(db, "auto_b", "automatic")
    _add_variant(db, "man_c", "manual")
    meta = {
        "make": "TestMake", "model": "TestModel", "year": 2020,
        "fuel_type": "Benzin", "transmission": "Otomatik",
    }
    r = match_variant(meta, db)
    assert r.method == "ambiguous"
    assert set(r.variant_ids) == {"auto_a", "auto_b"}
    assert r.tx_mismatch is False
    assert "tx_coverage_gap:" not in r.notes


# ── /analyze propagation + log signal ─────────────────────────────────────────

def _post(client, meta):
    return client.post("/analyze", json={
        "listing_url": "https://www.sahibinden.com/ilan/x",
        "ad_metadata": meta,
    })


def test_analyze_mismatch_surfaces_caveat_and_logs_gap(db, megane4_variants, monkeypatch, tmp_path):
    log_path = tmp_path / "analyses.jsonl"
    monkeypatch.setattr(config, "ANALYSES_LOG_PATH", log_path)
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        resp = _post(client, {
            "make": "Renault", "model": "Megane", "year": 2020,
            "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
            "transmission": "Otomatik",
        })
        assert resp.status_code == 200
        body = resp.json()
        # Match itself is unchanged — still k9k_110.
        assert body["matched_variant_ids"] == ["megane4_k9k_110"]
        # Buyer-visible caveat present in the summary the UI renders.
        assert TX_MISMATCH_CAVEAT in body["summary"]
        # The stable gap signal reached the analysis log.
        assert "tx_coverage_gap:" in log_path.read_text()
    finally:
        app.dependency_overrides.clear()


def test_analyze_matching_transmission_has_no_caveat(db, megane4_variants, monkeypatch, tmp_path):
    log_path = tmp_path / "analyses.jsonl"
    monkeypatch.setattr(config, "ANALYSES_LOG_PATH", log_path)
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        resp = _post(client, {
            "make": "Renault", "model": "Megane", "year": 2020,
            "fuel_type": "Dizel", "engine_volume_cc": 1461, "power_hp": 110,
            "transmission": "Manuel",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["matched_variant_ids"] == ["megane4_k9k_110"]
        assert TX_MISMATCH_CAVEAT not in body["summary"]
        assert "tx_coverage_gap:" not in log_path.read_text()
    finally:
        app.dependency_overrides.clear()
