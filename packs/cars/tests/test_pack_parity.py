"""Parity: does the pack answer like the engine it replaces?

This is the gate the whole migration turns on. It replays real listings —
the five curated gold fixtures plus every payload in `logs/analyses.jsonl` —
through **both** engines and compares.

It does not demand identical output, and it should not. Three divergences are
deliberate decisions recorded in the backlog, and asserting them away would
mean asserting the pivot away:

1. **Status became rank (B26/B32).** The old resolver refused to serve any
   high-severity claim that was not `verified`, and 696 of 699 claims sit at
   `review`. With no authority there is nobody to promote a claim, so review
   state became a rank multiplier. The new engine therefore serves strictly
   more, ranked lower — which is the point.

2. **Year windows became soft (B9).** Where the old matcher rejected a listing
   whose year fell outside the catalogued production window, the new one
   matches and flags it. A year one off is far more often a catalog gap than a
   different car.

3. **Part attribution got stricter.** See `KNOWN_ATTRIBUTION_FIXES`.

What it *does* demand is the thing that would actually hurt a buyer: nothing
the old engine surfaced may vanish.
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
from kriko.lookup import lookup
from kriko.lookup.query import Query
from kriko.store import packstore
from kriko.store.db import connect
from kriko.text.title_sim import title_similar
from packs.cars.build import build

REPO = Path(__file__).resolve().parent.parent.parent.parent
GOLD = REPO / "backend" / "tests" / "fixtures" / "serving_gold"
ANALYSES = REPO / "logs" / "analyses.jsonl"
GOLDEN = Path(__file__).parent / "fixtures" / "parity_golden.jsonl"

# Claims the old engine served that the new one deliberately does not.
#
# Every one is filed in the h5f (petrol 1.2 TCe) part file but describes the
# DC4 gearbox, which petrol and diesel Méganes share. The old sync linked them
# to a k9k *diesel* car that is not fitted with the h5f engine at all. The new
# engine reaches claims through fitment only, so it serves the same failures
# from the DC4 part where they belong — verified by
# `test_the_gearbox_failures_are_still_covered_from_the_right_part`.
#
# This is an attribution fix, not a loss. It is enumerated rather than
# generalised because it must shrink to nothing when the catalog is refiled,
# and a test that silently tolerated a growing list would hide that.
KNOWN_ATTRIBUTION_FIXES = {
    "h5f EDC transmission shift jerkiness",
    "h5f EDC gearbox: jerky shifts and knocking noise",
    "DSG mechatronic failures in automatic transmissions",
    "Clutch Squeaking Noise (Manual Transmissions)",
    "Clutch-Related Issues (Manual Transmission Models)",
}


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def old_engine():
    """A DB synced exactly as production does — the reference implementation."""
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    for table in (Variant.__table__, Claim.__table__,
                  ClaimVariant.__table__, ClaimSource.__table__):
        table.create(engine, checkfirst=True)
    session = Session(engine)
    sync_variants(session)
    sync_claims(session)
    sync_parts(session)
    session.flush()
    yield session
    session.rollback()
    engine.dispose()


@pytest.fixture(scope="module")
def new_engine(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    pack, report = build(out / "cars.kpack")
    store = connect(out / "store.sqlite")
    packstore.install(store, pack)
    yield store, {v: k for k, v in report["id_map"].items()}
    store.close()


@pytest.fixture(scope="module")
def cases():
    out = []
    for path in sorted(GOLD.glob("*.json")):
        out.append((path.stem, json.loads(path.read_text())["ad_metadata"]))
    if ANALYSES.exists():
        for line in ANALYSES.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            meta = record.get("ad_metadata")
            if meta:
                out.append((str(record.get("id", "log"))[:8], meta))
    assert len(out) >= 50, f"only {len(out)} replay cases — parity needs real traffic"
    return out


# ── the two engines, driven the same way ─────────────────────────────────

def _old(meta, session):
    meta = recover_listing_fields(dict(meta))
    year = meta.get("year")
    ctx = ListingContext(
        mileage_km=meta.get("mileage_km"),
        age_years=(date.today().year - year) if year else None,
        model_year=year,
        annual_km=None,
        fuel_type=meta.get("fuel_type"),
        transmission=meta.get("transmission"),
        description=meta.get("description", ""),
        equipment=meta.get("equipment") or [],
    )
    match = match_variant(meta, session)
    served = resolve_claims(match, session, ctx)
    return set(match.variant_ids or []), [(r.claim.title, r.claim.domain) for r in served]


def _new(store, meta, limit=1000):
    year = meta.get("year")
    identity = {"make": meta.get("make"), "model": meta.get("model"),
                "fuel": meta.get("fuel_type"),
                "displacement_cc": meta.get("engine_volume_cc"),
                "power_min_hp": meta.get("power_hp"),
                "transmission": meta.get("transmission"),
                "build_year": year}
    context = {"usage_km": meta.get("mileage_km"),
               "age_years": (date.today().year - year) if year else None,
               "build_year": year,
               "free_text": meta.get("description", ""),
               "equipment": meta.get("equipment") or []}
    return lookup(store, Query(
        kind="product",
        identity={k: v for k, v in identity.items() if v not in (None, "")},
        context={k: v for k, v in context.items() if v not in (None, "", [])},
        limit=limit))


# ── the gates ────────────────────────────────────────────────────────────

def test_wherever_the_old_engine_matched_the_new_one_matches_identically(
        old_engine, new_engine, cases):
    """The load-bearing assertion. A different car means every claim is wrong."""
    store, to_legacy = new_engine
    mismatches = []
    checked = 0

    for name, meta in cases:
        old_variants, _ = _old(meta, old_engine)
        if not old_variants:
            continue          # old found nothing; see the B9 test below
        checked += 1
        new_variants = {to_legacy.get(s, s) for s in _new(store, meta).resolution.subject_ids}
        if old_variants != new_variants:
            mismatches.append(f"{name}: old={sorted(old_variants)} new={sorted(new_variants)}")

    assert checked >= 40, f"only {checked} cases where the old engine matched"
    assert mismatches == [], (
        "the new engine resolved a different car:\n  " + "\n  ".join(mismatches))


def test_no_claim_the_old_engine_served_disappears(old_engine, new_engine, cases):
    """Nothing a buyer used to see may silently vanish.

    Represented, not identical: the new engine may surface the same failure
    under a near-duplicate title from a different pack or part, which is what
    read-time clustering is for. A claim counts as represented when a claim in
    the same domain has a similar title.
    """
    store, _ = new_engine
    lost: dict[str, int] = {}
    checked = 0

    for _, meta in cases:
        _, old_claims = _old(meta, old_engine)
        if not old_claims:
            continue
        new_claims = [(c.title, c.domain) for c in _new(store, meta).claims]
        for title, domain in old_claims:
            checked += 1
            if any(title == other or (domain == other_domain
                                      and title_similar(title, other))
                   for other, other_domain in new_claims):
                continue
            lost[title] = lost.get(title, 0) + 1

    assert checked > 1_000, f"only {checked} claim instances checked"
    unexplained = {t: n for t, n in lost.items() if t not in KNOWN_ATTRIBUTION_FIXES}
    assert unexplained == {}, (
        "claims the old engine served are unrepresented and unexplained:\n  "
        + "\n  ".join(f"x{n} {t}" for t, n in sorted(unexplained.items())))


def test_the_gearbox_failures_are_still_covered_from_the_right_part(new_engine):
    """The other half of KNOWN_ATTRIBUTION_FIXES: the failures are not lost.

    The old engine served DC4 gearbox faults to a diesel Mégane out of the h5f
    *petrol engine's* part file — a car not fitted with that engine at all. The
    new engine reaches claims through fitment, so the same faults arrive from
    the DC4 part, where they belong.
    """
    store, _ = new_engine
    result = _new(store, {"make": "Renault", "model": "Megane",
                          "fuel_type": "Dizel", "engine_volume_cc": 1461,
                          "power_hp": 110, "transmission": "Otomatik",
                          "year": 2018, "mileage_km": 150_000}, limit=100)

    # Transmission-domain claims may legitimately come from several parts — the
    # body-electrics file carries gear-selector wiring, for instance. What
    # matters is that the DC4 gearbox itself is reached and answers.
    from_dc4 = [c for c in result.claims
                if "DC4" in c.subject_label or "EDC" in c.subject_label]
    assert len(from_dc4) >= 8, "the DC4 gearbox's own claims must reach this car"
    assert any("jerk" in c.title.lower() or "shift" in c.title.lower()
               for c in from_dc4), "the shift-quality failure must still surface"


def test_the_new_engine_matches_some_listings_the_old_one_rejected(
        old_engine, new_engine, cases):
    """B9, asserted rather than assumed.

    A listing whose year sits outside the catalogued window used to be dropped.
    It now matches and carries a flag, because a year one off is far more often
    a gap in our catalog than a different car. If this ever returns zero, the
    year window has quietly gone hard again.
    """
    store, _ = new_engine
    recovered = 0
    for _, meta in cases:
        old_variants, _ = _old(meta, old_engine)
        if old_variants:
            continue
        if _new(store, meta).resolution.subject_ids:
            recovered += 1
    assert recovered > 0


def test_review_status_lowers_rank_instead_of_hiding_the_claim(new_engine):
    """B26, asserted. 696 of 699 claims are unreviewed; none may be hidden."""
    store, _ = new_engine
    total = store.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    assert total == 699, "every claim in the catalog must be exported"

    confidences = [r[0] for r in store.execute(
        "SELECT DISTINCT author_confidence FROM claims WHERE author_confidence IS NOT NULL")]
    assert confidences, "status must survive as rank"
    assert min(confidences) > 0, "no exported claim may be rank-zeroed"


# ── the frozen record ────────────────────────────────────────────────────

def test_golden_output_is_stable(new_engine, cases):
    """Freeze what the new engine answers, while the old one still exists.

    Phase 6 deletes `backend/`, and every test above dies with it. This one
    survives, because it compares the new engine against a recording of itself
    made while the comparison was still possible. Without this file the largest
    deletion in the project would have no regression net at all.

    Regenerate deliberately: `pytest --regenerate-golden` after an intended
    serving change, and read the diff.
    """
    store, to_legacy = new_engine
    actual = []
    for name, meta in cases:
        result = _new(store, meta, limit=8)
        actual.append({
            "case": name,
            "variants": sorted(to_legacy.get(s, s) for s in result.resolution.subject_ids),
            "method": result.resolution.method,
            "coverage": result.coverage,
            "claims": [c.title for c in result.claims],
        })

    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True)
                      for row in actual) + "\n", encoding="utf-8")
        pytest.skip(f"recorded {len(actual)} golden rows at {GOLDEN.name}")

    expected = [json.loads(line) for line in
                GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(actual) == len(expected)

    drifted = [f"{a['case']}: {a} != {e}"
               for a, e in zip(actual, expected) if a != e]
    assert drifted == [], (
        f"{len(drifted)} case(s) drifted from the golden record:\n  "
        + "\n  ".join(drifted[:5]))
