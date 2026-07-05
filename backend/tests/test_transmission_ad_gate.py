"""Tests for the ad-vs-catalog transmission mismatch gate (resolver.py).

Context: matcher.py matches a listing to a Variant on cc+hp+fuel+year alone;
_narrow_by_transmission is a *soft* filter that falls back to the unnarrowed
set when no candidate's cataloged transmission matches what the ad reports.
Concretely, the Golf 7 GTI catalog rows (golf7_ea888_220/230) are cataloged
automatic-only (DQ250/DQ381) even though both also shipped with a 6-speed
manual — so a real manual GTI ad still "exact"-matches the automatic row,
and every DQ250 claim linked to it would otherwise be served to a buyer
whose car has no DSG at all.

_passes_transmission_gate hides just the transmission-mechanism-specific
claims in that case (not the whole match — engine-only claims like turbo/
timing-chain issues still apply regardless of gearbox), using two
independent signals:
  1. Provenance: the claim reached this variant via a dedicated automatic
     gearbox part (grounding_note names a "transmission"-type part whose
     part_id isn't "manual") — true regardless of wording.
  2. Text: a claim filed under a *different* part (e.g. electrical) but
     whose own title/rationale names the mechanism (DSG, mechatronic, ...).
"""

import pytest

from backend.core.context import ListingContext
from backend.core.matcher import MatchResult
from backend.core.resolver import resolve_claims
from backend.db.models import Claim, ClaimSource, ClaimVariant


def _claim(id_, title, rationale="", **kwargs):
    return Claim(
        id=id_, claim_key=id_, version=1, is_current=True,
        title=title, domain=kwargs.pop("domain", "transmission"),
        severity=kwargs.pop("severity", "medium"), confidence=0.85,
        rationale=rationale or title,
        inspection_advice="Inspect accordingly.",
        status="verified", promoted_by="human",
        kind="known_issue",
        **kwargs,
    )


@pytest.fixture
def dq250_provenance_claim(db, megane4_variants):
    """A DQ250-file claim whose OWN wording says nothing about DSG at all —
    only its fitment provenance (grounding_note) marks it as automatic-only.
    Mirrors the real dq250.yaml claim "Clutch Pack Wear in High-Torque
    Applications", which text-regex alone would miss.
    """
    claim = _claim("dq250_clutch_pack_v1", "Clutch Pack Wear in High-Torque Applications",
                    "The clutch packs wear prematurely under sustained high-torque use.")
    db.add(claim)
    db.add(ClaimVariant(
        claim_id=claim.id, variant_id="megane4_k9k_90",
        grounding_note="Part fitment: dq250 (transmission)",
    ))
    db.add(ClaimSource(claim_id=claim.id, source_url="https://example.com", quote="Worn clutch packs reported."))
    db.flush()
    return claim


@pytest.fixture
def dsg_text_only_claim(db, megane4_variants):
    """A claim filed under a non-transmission part (electrical) whose own
    text names the DSG mechanism — provenance alone wouldn't catch this,
    only the shared AUTO_ONLY_RE vocabulary.
    """
    claim = _claim("elec_dsg_hesitation_v1", "DSG gearbox hesitation or rough shifting",
                    "Electrical gremlins cause the DSG gearbox to hesitate.", domain="electrical")
    db.add(claim)
    db.add(ClaimVariant(
        claim_id=claim.id, variant_id="megane4_k9k_90",
        grounding_note="Part fitment: golf7_elec (electrical)",
    ))
    db.add(ClaimSource(claim_id=claim.id, source_url="https://example.com", quote="DSG hesitates."))
    db.flush()
    return claim


@pytest.fixture
def engine_only_claim(db, megane4_variants):
    """A genuine engine-domain claim — must survive the gate regardless of
    what the ad's transmission field says, since it applies to any gearbox."""
    claim = _claim("engine_turbo_v1", "Turbocharger wastegate actuator failure",
                    "The wastegate actuator sticks, causing boost issues.", domain="engine")
    db.add(claim)
    db.add(ClaimVariant(
        claim_id=claim.id, variant_id="megane4_k9k_90",
        grounding_note="Part fitment: k9k (engine)",
    ))
    db.add(ClaimSource(claim_id=claim.id, source_url="https://example.com", quote="Wastegate sticks."))
    db.flush()
    return claim


@pytest.fixture
def manual_only_text_claim(db, megane4_variants):
    """A claim naming a manual-only mechanism (clutch pedal) — the symmetric
    direction: should be hidden when the ad states automatic."""
    claim = _claim("manual_clutch_pedal_v1", "Clutch pedal feels spongy over time",
                    "The clutch pedal loses feel as the cable stretches.")
    db.add(claim)
    db.add(ClaimVariant(
        claim_id=claim.id, variant_id="megane4_k9k_90",
        grounding_note="Part fitment: k9k (engine)",
    ))
    db.add(ClaimSource(claim_id=claim.id, source_url="https://example.com", quote="Pedal feels soft."))
    db.flush()
    return claim


def _ids(db, ctx=None, match_variant="megane4_k9k_90"):
    match = MatchResult([match_variant], "exact", "")
    return [r.claim.id for r in resolve_claims(match, db, ctx)]


def test_provenance_only_claim_hidden_on_manual_ad(db, dq250_provenance_claim):
    """A DQ250-fitment claim with no DSG wording in its own text is still
    hidden for a manual-stated ad, via grounding_note provenance."""
    ctx = ListingContext(transmission="Manuel")
    ids = _ids(ctx=ctx, db=db)
    assert "dq250_clutch_pack_v1" not in ids


def test_provenance_only_claim_shown_on_automatic_ad(db, dq250_provenance_claim):
    ctx = ListingContext(transmission="Otomatik")
    ids = _ids(ctx=ctx, db=db)
    assert "dq250_clutch_pack_v1" in ids


def test_text_only_claim_hidden_on_manual_ad(db, dsg_text_only_claim):
    """A non-transmission-part claim that names DSG in its own text is still
    caught by the text layer even though provenance wouldn't flag it."""
    ctx = ListingContext(transmission="Manuel")
    ids = _ids(ctx=ctx, db=db)
    assert "elec_dsg_hesitation_v1" not in ids


def test_engine_claim_unaffected_by_manual_ad(db, engine_only_claim):
    """Gearbox-agnostic engine claims are never gated by transmission."""
    ctx = ListingContext(transmission="Manuel")
    ids = _ids(ctx=ctx, db=db)
    assert "engine_turbo_v1" in ids


def test_engine_claim_unaffected_by_automatic_ad(db, engine_only_claim):
    ctx = ListingContext(transmission="Otomatik")
    ids = _ids(ctx=ctx, db=db)
    assert "engine_turbo_v1" in ids


def test_failopen_when_ad_transmission_missing(db, dq250_provenance_claim):
    """No ad-side transmission signal at all -> never hide (fail open,
    mirrors the equipment gate's missing-data philosophy)."""
    ctx = ListingContext(transmission=None)
    ids = _ids(ctx=ctx, db=db)
    assert "dq250_clutch_pack_v1" in ids


def test_failopen_when_no_context(db, dq250_provenance_claim):
    ids = _ids(ctx=None, db=db)
    assert "dq250_clutch_pack_v1" in ids


def test_manual_only_claim_hidden_on_automatic_ad(db, manual_only_text_claim):
    """Symmetric direction: manual-mechanism wording gated out when the ad
    itself states an automatic transmission."""
    ctx = ListingContext(transmission="Otomatik")
    ids = _ids(ctx=ctx, db=db)
    assert "manual_clutch_pedal_v1" not in ids


def test_manual_only_claim_shown_on_manual_ad(db, manual_only_text_claim):
    ctx = ListingContext(transmission="Manuel")
    ids = _ids(ctx=ctx, db=db)
    assert "manual_clutch_pedal_v1" in ids
