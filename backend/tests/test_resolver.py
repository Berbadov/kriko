"""Resolver tests: verified-claim invariant, exact and union-for-ambiguous logic."""

import pytest
from backend.core.context import ListingContext
from backend.core.matcher import MatchResult
from backend.core.resolver import ClaimResult, resolve_claims, _servable_claims_for
from backend.db.models import Claim, ClaimSource, ClaimVariant, Variant


def test_exact_match_returns_verified_claims(db, megane4_claims):
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db)
    titles = [r.claim.title for r in results]
    # k9k_90 should get injector, EGR, and A/C condenser claims
    assert any("injector" in t.lower() for t in titles)
    assert any("egr" in t.lower() for t in titles)


def test_ambiguous_match_returns_intersection(db, megane4_claims):
    # Both k9k_90 and k9k_110 share injector, EGR, and A/C condenser claims.
    match = MatchResult(["megane4_k9k_90", "megane4_k9k_110"], "ambiguous", "")
    results = resolve_claims(match, db)
    # Should still include the shared claims (verified for both)
    assert len(results) >= 2
    titles = [r.claim.title for r in results]
    assert any("injector" in t.lower() for t in titles)
    assert any("egr" in t.lower() for t in titles)


def test_ambiguous_match_includes_single_variant_claims(db, megane4_claims, db_add_unique_claim):
    # Ambiguous resolution uses union: a claim grounded only to k9k_90 should
    # still appear when matching ambiguously between k9k_90 and k9k_110 — the
    # buyer needs to know about all possible risks, not just the intersection.
    match = MatchResult(["megane4_k9k_90", "megane4_k9k_110"], "ambiguous", "")
    results = resolve_claims(match, db)
    ids = [r.claim.id for r in results]
    assert "megane4_k9k_90_only_v1" in ids


@pytest.fixture
def db_add_unique_claim(db, megane4_variants):
    """Add a claim verified only for megane4_k9k_90 (used in intersection test)."""
    claim = Claim(
        id="megane4_k9k_90_only_v1",
        claim_key="megane4_k9k_90_only",
        version=1, is_current=True,
        title="Test claim unique to k9k_90",
        domain="engine", severity="low",
        confidence=0.70,
        rationale="Test only.",
        inspection_advice="Test only.",
        status="verified",
        promoted_by="human",
        kind="known_issue",
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://example.com", quote="Test quote.",
    ))
    db.flush()
    return claim


def test_no_match_returns_empty(db, megane4_claims):
    match = MatchResult([], "no_match", "")
    assert resolve_claims(match, db) == []


def test_empty_variant_ids_returns_empty(db, megane4_claims):
    match = MatchResult([], "inconsistent_listing", "")
    assert resolve_claims(match, db) == []


def test_draft_claim_not_served(db, megane4_variants):
    """Claims with status != 'verified' must never be served."""
    claim = Claim(
        id="draft_claim_v1", claim_key="draft_claim", version=1, is_current=True,
        title="Draft claim should not appear",
        domain="engine", severity="low", confidence=0.5,
        rationale="Draft.", inspection_advice="Draft.",
        status="draft",  # NOT verified
        promoted_by=None,
        kind="known_issue",
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://example.com", quote="Quote.",
    ))
    db.flush()

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db)
    assert all(r.claim.id != "draft_claim_v1" for r in results)


@pytest.mark.parametrize("status", ["review", "held"])
def test_review_and_held_claims_are_served(db, megane4_variants, status):
    """review/held are now served (labelled 'reported' downstream), unlike draft."""
    claim = Claim(
        id=f"{status}_claim_v1", claim_key=f"{status}_claim", version=1, is_current=True,
        title=f"{status} claim should appear",
        domain="engine", severity="medium", confidence=0.6,
        rationale="Reported.", inspection_advice="Check it.",
        status=status, promoted_by="pending_human",
        kind="known_issue",
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://blog.example", quote="Quote.",
    ))
    db.flush()

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ids = [r.claim.id for r in resolve_claims(match, db)]
    assert f"{status}_claim_v1" in ids


def test_old_version_claim_not_served(db, megane4_variants):
    """Claims with is_current=False must never be served."""
    claim = Claim(
        id="old_claim_v1", claim_key="old_claim", version=1, is_current=False,
        title="Old version claim should not appear",
        domain="engine", severity="medium", confidence=0.7,
        rationale="Old.", inspection_advice="Old.",
        status="verified",
        promoted_by="human",
        kind="known_issue",
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://example.com", quote="Quote.",
    ))
    db.flush()

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db)
    assert all(r.claim.id != "old_claim_v1" for r in results)


def test_sourceless_claim_not_served(db, megane4_variants):
    """known_issue claims with zero source rows must not be served (invariant re-check)."""
    claim = Claim(
        id="no_source_v1", claim_key="no_source", version=1, is_current=True,
        title="Claim with no sources",
        domain="engine", severity="high", confidence=0.8,
        rationale="No sources.", inspection_advice="No sources.",
        status="verified",
        promoted_by="human",
        kind="known_issue",
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    # Deliberately no ClaimSource row
    db.flush()

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db)
    assert all(r.claim.id != "no_source_v1" for r in results)


@pytest.mark.parametrize("status", ["review", "held"])
def test_high_severity_unreviewed_claims_not_served(db, megane4_variants, status):
    """docs/design_flaws.md Flaw 4: severity=='high' claims sitting at
    review/held (promoted_by=pending_human, i.e. the human sign-off never
    happened) must be withheld — unlike medium/low, which still serve as
    'reported' (see test_review_and_held_claims_are_served)."""
    claim = Claim(
        id=f"high_{status}_v1", claim_key=f"high_{status}", version=1, is_current=True,
        title=f"High severity {status} claim should NOT appear",
        domain="engine", severity="high", confidence=0.6,
        rationale="Unreviewed high severity.", inspection_advice="Check it.",
        status=status, promoted_by="pending_human",
        kind="known_issue",
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://blog.example", quote="Quote.",
    ))
    db.flush()

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ids = [r.claim.id for r in resolve_claims(match, db)]
    assert f"high_{status}_v1" not in ids


def test_high_severity_verified_claim_still_served(db, megane4_variants):
    """The gate only withholds unreviewed statuses — a properly verified
    high-severity claim (human/corroboration-backed) still serves."""
    claim = Claim(
        id="high_verified_v1", claim_key="high_verified", version=1, is_current=True,
        title="High severity verified claim should appear",
        domain="engine", severity="high", confidence=0.9,
        rationale="Corroborated high severity.", inspection_advice="Check it.",
        status="verified", promoted_by="human",
        kind="known_issue",
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://blog.example", quote="Quote.",
    ))
    db.flush()

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ids = [r.claim.id for r in resolve_claims(match, db)]
    assert "high_verified_v1" in ids


def test_high_severity_maintenance_claim_still_served(db, megane4_variants):
    """Maintenance claims are exempt from the severity gate — their trust
    model is the manufacturer interval, not LLM corroboration count (see
    resolver.py's _servable_claims_for docstring)."""
    claim = Claim(
        id="high_maint_v1", claim_key="high_maint", version=1, is_current=True,
        title="High severity maintenance claim should appear",
        domain="engine", severity="high", confidence=0.9,
        rationale="Belt due at 90k km.", inspection_advice="Ask for invoice.",
        status="held", promoted_by="human",
        kind="maintenance",
        maintenance_data={"interval_km": 90000, "evidence_keywords": []},
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    # Deliberately no ClaimSource — maintenance claims are exempt from has_source too.
    db.flush()

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    ctx = ListingContext(mileage_km=100000)
    ids = [r.claim.id for r in resolve_claims(match, db, ctx)]
    assert "high_maint_v1" in ids


def test_h5h_claims_served_for_h5h_variant(db, megane4_claims):
    match = MatchResult(["megane4_h5h_140"], "exact", "")
    results = resolve_claims(match, db)
    titles = [r.claim.title for r in results]
    # H5H uses DW5 (wet clutch EDC) — dry-clutch DC4 specific claims should NOT appear
    assert not any("dc4" in t.lower() or "dry clutch" in t.lower() for t in titles)
    # K9K diesel-specific claims should NOT appear for an H5H petrol variant
    assert not any("injector" in t.lower() for t in titles)


def test_h5f_gets_dc4_claims(db, megane4_claims):
    match = MatchResult(["megane4_h5f_100"], "exact", "")
    results = resolve_claims(match, db)
    titles = [r.claim.title for r in results]
    # H5F uses DC4 (dry clutch EDC) — dry-clutch claims should appear
    assert any("dc4" in t.lower() or "dry clutch" in t.lower() for t in titles)


def test_h5f_claims_not_in_h5h_result(db, megane4_claims):
    match = MatchResult(["megane4_h5h_115"], "exact", "")
    results = resolve_claims(match, db)
    ids = [r.claim.id for r in results]
    assert "megane4_h5f_timingchain_v1" not in ids


def test_diesel_variants_get_dpf_claim(db, megane4_claims):
    """DPF clogging claim should appear for all diesel Megane IV variants."""
    diesel_variant_ids = ["megane4_k9k_90", "megane4_k9k_110", "megane4_r9m_130"]
    for vid in diesel_variant_ids:
        match = MatchResult([vid], "exact", "")
        results = resolve_claims(match, db)
        titles = [r.claim.title for r in results]
        assert any("dpf" in t.lower() or "particulate" in t.lower() for t in titles), \
            f"DPF claim missing for {vid}"


def test_verified_claim_strength_is_confirmed(db, megane4_claims):
    """Verified claims must carry strength='confirmed'."""
    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db)
    confirmed = [r for r in results if r.claim.status == "verified"]
    assert all(r.strength == "confirmed" for r in confirmed)


def test_held_claim_strength_is_reported(db, megane4_variants):
    """held/review claims must carry strength='reported'."""
    claim = Claim(
        id="held_strength_v1", claim_key="held_strength", version=1, is_current=True,
        title="Held claim strength test",
        domain="engine", severity="medium", confidence=0.6,
        rationale="Reported.", inspection_advice="Check it.",
        status="held", promoted_by="pending_human",
        kind="known_issue",
    )
    db.add(claim)
    db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90"))
    db.add(ClaimSource(
        claim_id=claim.id,
        source_url="https://blog.example", quote="Quote.",
    ))
    db.flush()

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db)
    held = [r for r in results if r.claim.id == "held_strength_v1"]
    assert len(held) == 1
    assert held[0].strength == "reported"
