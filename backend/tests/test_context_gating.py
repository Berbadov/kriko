"""Tests for ListingContext-aware claim gating (Phase 1, 2 & 4).

Covers:
- applies_when mileage/age gating with fail-open on missing data
- maintenance claim due/not-due/evidence logic
- maintenance claims served without ClaimSource rows
- equipment gating (Phase 4): claims tagged requires_equipment are hidden when
  the listing's scraped equipment confirms the feature is absent, but shown
  when equipment wasn't scraped at all (fail-open on missing data, fail-closed
  only on a confirmed mismatch)
"""

import pytest
from backend.core.context import ListingContext
from backend.core.matcher import MatchResult
from backend.core.resolver import resolve_claims, _resolve_maintenance_strength
from backend.db.models import Claim, ClaimSource, ClaimVariant


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def k9k_mileage_gated_claim(db, megane4_variants):
    """A known_issue claim for K9K with applies_when min_mileage_km=80000."""
    claim = Claim(
        id="k9k_gated_v1", claim_key="k9k_gated", version=1, is_current=True,
        title="K9K mileage-gated test claim",
        domain="emissions", severity="medium", confidence=0.85,
        rationale="Relevant only above 80k km.",
        inspection_advice="Check at high mileage.",
        status="verified", promoted_by="human",
        kind="known_issue",
        min_mileage_km=80000,
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://example.com", quote="City cars over 80k should be checked.",
    ))
    db.flush()
    return claim


@pytest.fixture
def k9k_age_gated_claim(db, megane4_variants):
    """A known_issue claim for K9K with applies_when min_age_years=5."""
    claim = Claim(
        id="k9k_age_gated_v1", claim_key="k9k_age_gated", version=1, is_current=True,
        title="K9K age-gated test claim",
        domain="emissions", severity="medium", confidence=0.80,
        rationale="Relevant only for cars older than 5 years.",
        inspection_advice="Check on older cars.",
        status="verified", promoted_by="human",
        kind="known_issue",
        min_age_years=5,
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://example.com", quote="After 5 years this part degrades.",
    ))
    db.flush()
    return claim


@pytest.fixture
def k9k_year_windowed_claim(db, megane4_variants):
    """A known_issue claim scoped to model years 2019–2022 (a build-year defect
    fixed from MY2023 on an otherwise-identical part)."""
    claim = Claim(
        id="k9k_year_windowed_v1", claim_key="k9k_year_windowed", version=1, is_current=True,
        title="K9K model-year-windowed test claim",
        domain="emissions", severity="medium", confidence=0.80,
        rationale="Present on 2019–2022 builds, fixed from 2023.",
        inspection_advice="Relevant for 2019–2022 cars.",
        status="verified", promoted_by="human",
        kind="known_issue",
        applies_year_from=2019, applies_year_to=2022,
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://example.com", quote="2019-2022 builds affected, corrected from 2023.",
    ))
    db.flush()
    return claim


@pytest.fixture
def k9k_year_open_ended_claim(db, megane4_variants):
    """A known_issue claim scoped to model year 2023 onward (a facelift/ADAS
    fault introduced from MY2023, no upper bound)."""
    claim = Claim(
        id="k9k_year_open_v1", claim_key="k9k_year_open", version=1, is_current=True,
        title="K9K from-MY2023 test claim",
        domain="emissions", severity="medium", confidence=0.80,
        rationale="New fault from the 2023 refresh onward.",
        inspection_advice="Relevant for 2023-onward cars.",
        status="verified", promoted_by="human",
        kind="known_issue",
        applies_year_from=2023, applies_year_to=None,
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://example.com", quote="Introduced with the 2023 facelift.",
    ))
    db.flush()
    return claim


@pytest.fixture
def k9k_belt_maintenance_claim(db, megane4_variants):
    """A maintenance claim for K9K belt with NO ClaimSource rows."""
    claim = Claim(
        id="k9k_belt_v1", claim_key="k9k_belt", version=1, is_current=True,
        title="K9K timing belt maintenance test",
        domain="engine", severity="high", confidence=0.95,
        rationale="Belt due at 90k km or 5 years.",
        inspection_advice="Ask for belt replacement invoice.",
        status="held", promoted_by="human",
        kind="maintenance",
        maintenance_data={
            "interval_km": 90000,
            "interval_years": 5,
            "evidence_keywords": ["triger değiş", "kayış değiş", "timing belt changed"],
        },
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    # Deliberately NO ClaimSource — maintenance claims are exempt from has_source
    db.flush()
    return claim


@pytest.fixture
def sunroof_claim(db, megane4_variants):
    """A known_issue claim requiring the 'sunroof' equipment tag."""
    claim = Claim(
        id="sunroof_drain_v1", claim_key="sunroof_drain", version=1, is_current=True,
        title="Sunroof drain tube blockage",
        domain="body", severity="medium", confidence=0.85,
        rationale="Panoramic sunroof drain tubes clog and cause water ingress.",
        inspection_advice="Check sunroof drain tubes for blockage.",
        status="verified", promoted_by="human",
        kind="known_issue",
        requires_equipment=["sunroof"],
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://example.com", quote="Sunroof drain tubes clog on this model.",
    ))
    db.flush()
    return claim


# ── applies_when mileage gating ───────────────────────────────────────────────

def test_mileage_gate_shown(db, k9k_mileage_gated_claim):
    """Claim is shown when mileage exceeds the minimum threshold."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=190000)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_gated_v1" in ids


def test_mileage_gate_hidden(db, k9k_mileage_gated_claim):
    """Claim is hidden when mileage is below the minimum threshold."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=30000)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_gated_v1" not in ids


def test_mileage_gate_failopen_unknown_mileage(db, k9k_mileage_gated_claim):
    """Claim is shown when mileage is unknown (fail-open — never hide on missing data)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=None)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_gated_v1" in ids


def test_mileage_gate_failopen_no_ctx(db, k9k_mileage_gated_claim):
    """Claim is shown when no ListingContext is provided at all (fail-open)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db, ctx=None)
    ids = [r.claim.id for r in results]
    assert "k9k_gated_v1" in ids


def test_age_gate_hidden(db, k9k_age_gated_claim):
    """Claim is hidden when age_years is below the minimum threshold."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(age_years=3)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_age_gated_v1" not in ids


def test_age_gate_shown(db, k9k_age_gated_claim):
    """Claim is shown when age_years meets or exceeds the minimum threshold."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(age_years=7)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_age_gated_v1" in ids


def test_age_gate_failopen_unknown_age(db, k9k_age_gated_claim):
    """Claim is shown when age is unknown (fail-open)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(age_years=None)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_age_gated_v1" in ids


# ── applies_when model-year window gating ─────────────────────────────────────

def test_year_window_shown_in_window(db, k9k_year_windowed_claim):
    """Claim is shown when the listing's model year falls inside the window."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(model_year=2020)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_year_windowed_v1" in ids


def test_year_window_hidden_above(db, k9k_year_windowed_claim):
    """Claim is hidden when the model year is above the window (defect fixed)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(model_year=2023)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_year_windowed_v1" not in ids


def test_year_window_hidden_below(db, k9k_year_windowed_claim):
    """Claim is hidden when the model year is below the window (not yet affected)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(model_year=2017)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_year_windowed_v1" not in ids


def test_year_window_failopen_unknown_year(db, k9k_year_windowed_claim):
    """Claim is shown when the model year is unknown (fail-open — never hide on missing data)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(model_year=None)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_year_windowed_v1" in ids


def test_year_window_failopen_no_ctx(db, k9k_year_windowed_claim):
    """Claim is shown when no ListingContext is provided at all (fail-open)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db, ctx=None)
    ids = [r.claim.id for r in results]
    assert "k9k_year_windowed_v1" in ids


def test_year_window_open_ended_shown(db, k9k_year_open_ended_claim):
    """An open-ended (from=2023, to=None) claim is shown at/after the lower bound."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(model_year=2024)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_year_open_v1" in ids


def test_year_window_open_ended_hidden_below(db, k9k_year_open_ended_claim):
    """An open-ended (from=2023, to=None) claim is hidden below the lower bound."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(model_year=2022)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_year_open_v1" not in ids


def test_year_window_does_not_affect_untagged_claims(db, k9k_mileage_gated_claim):
    """A claim with no model-year window is unaffected by the listing's model year."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=190000, model_year=2015)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_gated_v1" in ids


def test_year_window_end_to_end_via_run_analysis(db, k9k_year_windowed_claim):
    """End-to-end: the /analyze path carries the raw listing year (meta['year'])
    into the window gate. A MY2019-2022 claim is hidden for a 2023 listing and
    shown for a 2020 listing — both years match the same K9K variant (2016-2023),
    so only the window differs."""
    from backend.api.main import run_analysis

    base = {
        "make": "Renault", "model": "Megane",
        "fuel_type": "diesel", "transmission": "manual",
        "engine_volume_cc": 1461, "power_hp": 90, "mileage_km": 50000,
    }
    _c, _m, served_2023, _r = run_analysis({**base, "year": 2023}, db)
    assert "k9k_year_windowed_v1" not in [r.claim.id for r in served_2023]

    _c, _m, served_2020, _r = run_analysis({**base, "year": 2020}, db)
    assert "k9k_year_windowed_v1" in [r.claim.id for r in served_2020]


# ── maintenance interval logic ────────────────────────────────────────────────

def test_maintenance_due_no_evidence(db, k9k_belt_maintenance_claim):
    """Maintenance claim due by km, no evidence in ad → strength='due'."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=100000, description="temiz araba, iyi bakımlı")
    results = resolve_claims(match, db, ctx)
    belt = [r for r in results if r.claim.id == "k9k_belt_v1"]
    assert len(belt) == 1
    assert belt[0].strength == "due"


def test_maintenance_due_with_evidence(db, k9k_belt_maintenance_claim):
    """Maintenance claim due by km, ad contains evidence keyword → strength='due_stated'."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    # Description contains "triger değiş" — evidence of recent service
    ctx = ListingContext(mileage_km=100000, description="triger değişti geçen ay, tam bakımlı")
    results = resolve_claims(match, db, ctx)
    belt = [r for r in results if r.claim.id == "k9k_belt_v1"]
    assert len(belt) == 1
    assert belt[0].strength == "due_stated"


def test_maintenance_not_due_hidden(db, k9k_belt_maintenance_claim):
    """Maintenance claim not due by km or age → hidden (not in results)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=50000, age_years=3)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_belt_v1" not in ids


def test_maintenance_due_by_age(db, k9k_belt_maintenance_claim):
    """Maintenance claim not due by km but due by age → shown as 'due'."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=50000, age_years=6)  # 6yr >= 5yr interval
    results = resolve_claims(match, db, ctx)
    belt = [r for r in results if r.claim.id == "k9k_belt_v1"]
    assert len(belt) == 1
    assert belt[0].strength == "due"


def test_maintenance_failopen_no_ctx(db, k9k_belt_maintenance_claim):
    """Maintenance claim shown as 'due' when no context is provided (fail-open)."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db, ctx=None)
    belt = [r for r in results if r.claim.id == "k9k_belt_v1"]
    assert len(belt) == 1
    assert belt[0].strength == "due"


def test_maintenance_failopen_unknown_mileage_and_age(db, k9k_belt_maintenance_claim):
    """Maintenance claim shown as 'due' when both mileage and age are unknown."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=None, age_years=None)
    results = resolve_claims(match, db, ctx)
    belt = [r for r in results if r.claim.id == "k9k_belt_v1"]
    assert len(belt) == 1
    assert belt[0].strength == "due"


def test_maintenance_no_source_required(db, k9k_belt_maintenance_claim):
    """Maintenance claims bypass the has_source filter and are served without ClaimSource rows."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=100000)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    # Should be served even though there are no ClaimSource rows
    assert "k9k_belt_v1" in ids


# ── _resolve_maintenance_strength unit tests ─────────────────────────────────

def test_resolve_maintenance_strength_direct():
    """Unit test _resolve_maintenance_strength directly."""
    claim = Claim(
        id="test", claim_key="test", version=1, is_current=True,
        title="Test", domain="engine", severity="high", confidence=0.9,
        rationale="Test", inspection_advice="Test",
        status="held", kind="maintenance",
        maintenance_data={
            "interval_km": 90000,
            "interval_years": 5,
            "evidence_keywords": ["triger değiş", "timing belt changed"],
        },
    )

    # Due by km, no evidence
    ctx = ListingContext(mileage_km=100000, description="clean car")
    assert _resolve_maintenance_strength(claim, ctx) == "due"

    # Due by km, evidence present
    ctx = ListingContext(mileage_km=100000, description="triger değiş yapıldı")
    assert _resolve_maintenance_strength(claim, ctx) == "due_stated"

    # Not due
    ctx = ListingContext(mileage_km=50000, age_years=2)
    assert _resolve_maintenance_strength(claim, ctx) is None

    # Fail-open: no data
    assert _resolve_maintenance_strength(claim, None) == "due"


# ── equipment gating (Phase 4) ────────────────────────────────────────────────

def test_equipment_gate_hidden_when_confirmed_absent(db, sunroof_claim):
    """Claim requiring sunroof is hidden when the listing's equipment block was
    scraped and does not mention a sunroof — fail CLOSED on confirmed mismatch."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(equipment={"Exterior": ["Alloy Wheels", "LED Headlights"]})
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "sunroof_drain_v1" not in ids


def test_equipment_gate_shown_when_present(db, sunroof_claim):
    """Claim requiring sunroof is shown when the listing's equipment mentions it."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(equipment={"Exterior": ["Panoramik Cam Tavan", "Alloy Wheels"]})
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "sunroof_drain_v1" in ids


def test_equipment_gate_failopen_no_equipment_scraped(db, sunroof_claim):
    """Claim requiring sunroof is shown when equipment wasn't scraped at all
    (None) — never hide on missing data, only on a confirmed mismatch."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(equipment=None)
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "sunroof_drain_v1" in ids


def test_equipment_gate_failopen_empty_equipment_dict(db, sunroof_claim):
    """An empty equipment dict ({}) is treated the same as None — extraction
    producing nothing is indistinguishable from extraction not running."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(equipment={})
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "sunroof_drain_v1" in ids


def test_equipment_gate_failopen_no_ctx(db, sunroof_claim):
    """Claim requiring sunroof is shown when no ListingContext is provided at all."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db, ctx=None)
    ids = [r.claim.id for r in results]
    assert "sunroof_drain_v1" in ids


def test_equipment_gate_does_not_affect_untagged_claims(db, k9k_mileage_gated_claim):
    """A claim with no requires_equipment tags is unaffected by equipment gating."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=190000, equipment={"Exterior": ["Alloy Wheels"]})
    results = resolve_claims(match, db, ctx)
    ids = [r.claim.id for r in results]
    assert "k9k_gated_v1" in ids
