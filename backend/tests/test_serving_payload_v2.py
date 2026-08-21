"""Serving payload v2 (Phase 3): component passthrough, visual-detection
suppression, relevance_score, why_shown, and subsystem grouping.

The suppression contract under test:
  * a claim whose registry component is detection "visual" ranks down by 0.35
    (VISUAL_DETECTION_FACTOR) — it is NEVER dropped, and only when the claim
    has a component_id AND a listing context exists;
  * relevance_score = severity weight (low 0.3 / medium 0.6 / high 1.0)
    × mileage-gate match (satisfied 1.0 / unknown 0.7 fail-open)
    × detection factor (visual 0.35 / else 1.0);
  * why_shown explains config match, mileage gate, and detection;
  * the response carries subsystems[] alongside the flat risks[] (backward
    compat for the current extension).
"""

import pytest

from backend.api.main import run_analysis
from backend.core.resolver import VISUAL_DETECTION_FACTOR, resolve_claims
from backend.core.matcher import MatchResult
from backend.core.context import ListingContext
from backend.db.models import Claim, ClaimSource, ClaimVariant
from backend.sync import _upsert_part_claim


def _add_claim(
    db, *, id, claim_key=None, severity="medium", domain="engine",
    component_id=None, detection=None, subsystem=None,
    min_mileage_km=None, variant_ids=("megane4_k9k_90",), status="verified",
):
    c = Claim(
        id=id, claim_key=claim_key or id, version=1, is_current=True,
        title=id.replace("_", " "), domain=domain, severity=severity,
        confidence=0.8, rationale="Rationale", inspection_advice="Advice",
        status=status, kind="known_issue",
        component_id=component_id, detection=detection, subsystem=subsystem,
        min_mileage_km=min_mileage_km,
    )
    db.add(c)
    db.flush()
    for v in variant_ids:
        db.add(ClaimVariant(claim_id=c.id, variant_id=v, grounding_note="test-mock"))
    db.add(ClaimSource(claim_id=c.id, source_url="https://example.com", quote="q", independent=True))
    db.flush()
    return c


def _listing(**over):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2019,
        "fuel_type": "Dizel", "transmission": "Manuel",
        "engine_volume_cc": 1461, "power_hp": 90, "mileage_km": 187000,
    }
    meta.update(over)
    return meta


# ── sync passthrough ──────────────────────────────────────────────────────────

def test_sync_fills_detection_and_subsystem_from_registry(db):
    claim_data = {
        "title": "Oil consumption", "domain": "engine", "severity": "medium",
        "rationale": "r", "inspection_advice": "i",
        "component_id": "engine_oil_consumption",
    }
    obj = _upsert_part_claim(db, "test_oil_v1", claim_data)
    assert obj.component_id == "engine_oil_consumption"
    assert obj.detection == "visual"
    assert obj.subsystem == "engine/lubrication"


def test_sync_tolerates_missing_component_id(db):
    """The v3 YAML migration runs in parallel — claims without component_id
    must sync fine and stay detection-neutral."""
    claim_data = {
        "title": "Some claim", "domain": "engine", "severity": "medium",
        "rationale": "r", "inspection_advice": "i",
    }
    obj = _upsert_part_claim(db, "test_plain_v1", claim_data)
    assert obj.component_id is None
    assert obj.detection is None
    assert obj.subsystem is None


def test_sync_tolerates_unknown_component_id(db):
    claim_data = {
        "title": "Some claim", "domain": "engine", "severity": "medium",
        "rationale": "r", "inspection_advice": "i",
        "component_id": "no_such_component",
    }
    obj = _upsert_part_claim(db, "test_unknown_v1", claim_data)
    assert obj.component_id == "no_such_component"
    assert obj.detection is None  # registry miss → detection-neutral
    assert obj.subsystem is None


def test_sync_uses_yaml_detection_when_registry_misses(db):
    """The v3 migration writes `detection:` into the part YAMLs alongside
    component_id — if the registry lags behind, the YAML's own value keeps
    suppression working instead of silently going neutral."""
    claim_data = {
        "title": "Some claim", "domain": "engine", "severity": "medium",
        "rationale": "r", "inspection_advice": "i",
        "component_id": "not_in_registry_yet", "detection": "visual",
    }
    obj = _upsert_part_claim(db, "test_yamldet_v1", claim_data)
    assert obj.detection == "visual"


def test_sync_registry_detection_wins_over_yaml(db):
    """The registry is the authority: when it knows the component, its
    detection value is stored even if the YAML disagrees."""
    claim_data = {
        "title": "Some claim", "domain": "engine", "severity": "medium",
        "rationale": "r", "inspection_advice": "i",
        "component_id": "engine_oil_consumption", "detection": "diagnostic",
    }
    obj = _upsert_part_claim(db, "test_regwins_v1", claim_data)
    assert obj.detection == "visual"


# ── resolver suppression ──────────────────────────────────────────────────────

def test_visual_claim_is_suppressed_not_dropped(db, megane4_variants):
    _add_claim(db, id="visual_oil_v1", component_id="engine_oil_consumption",
               detection="visual", subsystem="engine/lubrication")
    _add_claim(db, id="plain_v1")

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=187000, model_year=2019)
    results = {cr.claim.id: cr for cr in resolve_claims(match, db, ctx)}

    # Both serve — visual is ranked down, never dropped (fail-open principle).
    assert "visual_oil_v1" in results and "plain_v1" in results
    assert results["visual_oil_v1"].detection_factor == VISUAL_DETECTION_FACTOR
    assert results["plain_v1"].detection_factor == 1.0


def test_no_listing_context_means_no_suppression(db, megane4_variants):
    """No ctx → no suppression: the factor needs listing context to apply."""
    _add_claim(db, id="visual_oil_v1", component_id="engine_oil_consumption",
               detection="visual", subsystem="engine/lubrication")
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = {cr.claim.id: cr for cr in resolve_claims(match, db, None)}
    assert results["visual_oil_v1"].detection_factor == 1.0


def test_detection_without_component_id_is_neutral(db, megane4_variants):
    """detection set but component_id missing → neutral (sync fills the
    columns together, but the resolver must not trust that)."""
    _add_claim(db, id="orphan_detection_v1", detection="visual")
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=187000)
    results = {cr.claim.id: cr for cr in resolve_claims(match, db, ctx)}
    assert results["orphan_detection_v1"].detection_factor == 1.0


# ── API relevance_score / why_shown / grouping ────────────────────────────────

def test_relevance_score_formula_and_why_shown(db, megane4_variants):
    _add_claim(db, id="high_plain_v1", severity="high")
    _add_claim(db, id="medium_visual_v1", severity="medium",
               component_id="engine_oil_consumption",
               detection="visual", subsystem="engine/lubrication")
    _add_claim(db, id="low_plain_v1", severity="low")

    _, _, _, resp = run_analysis(_listing(), db)
    by_key = {r.claim_key: r for r in resp.risks}

    assert by_key["high_plain_v1"].relevance_score == 1.0          # 1.0 × 1.0 × 1.0
    assert by_key["medium_visual_v1"].relevance_score == pytest.approx(0.21)  # 0.6 × 1.0 × 0.35
    assert by_key["low_plain_v1"].relevance_score == 0.3           # 0.3 × 1.0 × 1.0

    # why_shown: config match on every card; the visual one explains itself.
    assert all(r.why_shown[0].startswith("Config match:") for r in resp.risks)
    visual_why = by_key["medium_visual_v1"].why_shown
    assert "standard inspection usually catches this — low priority" in visual_why

    # Ranked by relevance: high plain > low plain > medium visual.
    keys = [r.claim_key for r in resp.risks]
    assert keys == ["high_plain_v1", "low_plain_v1", "medium_visual_v1"]


def test_mileage_gate_satisfied_factor_and_string(db, megane4_variants):
    _add_claim(db, id="gated_v1", severity="high", min_mileage_km=120000)
    _, _, _, resp = run_analysis(_listing(mileage_km=187000), db)
    r = resp.risks[0]
    assert r.relevance_score == 1.0  # gate satisfied
    assert "187.000 km > 120.000 km threshold" in r.why_shown


def test_mileage_gate_unknown_fail_open_and_ranked_down(db, megane4_variants):
    _add_claim(db, id="gated_v1", severity="high", min_mileage_km=120000)
    _add_claim(db, id="ungated_v1", severity="high")
    _, _, _, resp = run_analysis(_listing(mileage_km=None), db)
    by_key = {r.claim_key: r for r in resp.risks}

    # Fail-open: the gated claim still serves, scored 1.0 × 0.7.
    gated = by_key["gated_v1"]
    assert gated.relevance_score == pytest.approx(0.7)
    assert "mileage unknown — shown by default" in gated.why_shown
    # ...but the confirmed-applicable same-severity risk outranks it (1.0 > 0.7).
    assert by_key["ungated_v1"].relevance_score == 1.0
    assert [r.claim_key for r in resp.risks] == ["ungated_v1", "gated_v1"]


def test_subsystems_grouping_with_other_bucket(db, megane4_variants):
    _add_claim(db, id="timing_v1", subsystem="engine/timing",
               component_id="engine_timing_chain", detection="diagnostic")
    _add_claim(db, id="oil_v1", subsystem="engine/lubrication",
               component_id="engine_oil_consumption", detection="visual")
    _add_claim(db, id="legacy_v1")  # no component → "other"

    _, _, _, resp = run_analysis(_listing(), db)
    groups = {g.name: g for g in resp.subsystems}
    assert set(groups) == {"engine/timing", "engine/lubrication", "other"}
    assert groups["engine/timing"].display_tr == "Motor"
    assert groups["other"].display_tr == "Diğer"

    # Every flat risk appears in exactly one group.
    grouped_keys = [r.claim_key for g in resp.subsystems for r in g.risks]
    assert sorted(grouped_keys) == sorted(r.claim_key for r in resp.risks)


def test_flat_risks_kept_for_backward_compat(db, megane4_variants):
    """The current extension reads `risks` only — the flat array must keep
    working, and subsystems[] must carry the same cards."""
    _add_claim(db, id="plain_v1")
    _, _, _, resp = run_analysis(_listing(), db)
    assert resp.risks and resp.risks[0].claim_key == "plain_v1"
    assert resp.risks[0].relevance_score is not None
    assert resp.subsystems[0].risks[0] is resp.risks[0]
