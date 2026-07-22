"""Regression net for the per-listing risk cap — the missing safety net around
the 2026-07-13 production incident.

A logged /analyze response served **39 risks (2 due + 37 reported)** when the
cap should have trimmed it to 8. ``_cap_risks`` provably reduces that exact
input to 8 (see test below) and was committed 2026-07-12 — a full day *before*
the 2026-07-13 incident record, and present in every commit checked out that
day (verified via `git show <commit>:backend/api/main.py`) — so this isn't
simply "the record predates the cap" by commit history. The serving code has
exactly one call site for the cap (``run_analysis``, unconditional, no
feature flag) and it is algorithmically sound, so the request must have been
handled by a process running older, already-superseded code — e.g. a
long-uptime container the extension's default API base (port 8000) talks to,
never rebuilt after the cap landed.
These tests pin the cap's contract at both the unit boundary and end-to-end
through ``/analyze`` — the level that would have caught the incident class —
so a future stale-deploy or in-code bypass regression fails here instead of
in production.

The end-to-end test is the one that mirrors the incident: >8 servable reported
claims for a single variant must arrive at the buyer as exactly 8.
"""

from fastapi.testclient import TestClient

from backend import config
from backend.api.main import MAX_RISKS_PER_LISTING, _cap_risks, app
from backend.api.schemas import RiskItem
from backend.db.models import Claim, ClaimSource, ClaimVariant
from backend.db.session import get_db


def _risk(title, strength="reported", consequence="medium", severity="medium"):
    return RiskItem(
        title=title, severity=severity, consequence=consequence, domain="engine",
        rationale="r", inspection_advice="a", source_count=0, strength=strength,
    )


# ── Unit: the exact incident shape at the cap boundary ───────────────────────

def test_cap_reproduces_39_risk_incident_returns_exactly_8():
    """The 2026-07-13 record verbatim: 2 due + 37 reported. Input is in the order
    run_analysis's sort produces (due — strength rank 1 — ahead of reported —
    rank 3; reported already ranked best-first). The cap must keep both due and
    the top 6 reported, dropping the other 31.
    """
    due = [_risk(f"due{i}", strength="due") for i in range(2)]
    reported = [_risk(f"rep{i:02d}", strength="reported") for i in range(37)]

    out = _cap_risks(due + reported, MAX_RISKS_PER_LISTING)

    assert len(out) == 8
    assert [r.title for r in out if r.strength == "due"] == ["due0", "due1"]
    assert [r.title for r in out if r.strength == "reported"] == [
        f"rep{i:02d}" for i in range(6)
    ]  # the 6 highest-ranked reported, in ranked order
    # None of the trimmed tail survived.
    assert not any(r.title == "rep06" for r in out)


# ── Unit: protected items are never hidden, even past the cap ────────────────

def test_protected_risks_beyond_the_cap_are_all_kept():
    """>8 protected risks (a genuinely high-mileage car with everything due) →
    all protected survive; reported get zero slots. Never hide a confirmed/due
    risk to meet a numeric ceiling (the deliberate 2026-07-12 policy).
    """
    protected = (
        [_risk(f"c{i}", strength="confirmed") for i in range(4)]
        + [_risk(f"d{i}", strength="due") for i in range(3)]
        + [_risk(f"ds{i}", strength="due_stated") for i in range(3)]
    )  # 10 protected
    reported = [_risk(f"rep{i}") for i in range(5)]

    out = _cap_risks(protected + reported, MAX_RISKS_PER_LISTING)

    assert len(out) == 10
    assert all(r.strength in ("confirmed", "due", "due_stated") for r in out)
    assert not any(r.strength == "reported" for r in out)  # no reported slots left


# ── Unit: an unknown strength value is handled safely ────────────────────────

def test_unknown_strength_is_trimmable_and_never_bypasses_the_cap():
    """Defensive contract for schema drift / bad data: a strength outside the
    known set is treated as NON-protected — subject to the cap, never mistaken
    for a protected item, and never able to bust the ceiling.
    """
    # Mixed with protected: unknown fills only the leftover reported-style slots.
    due = [_risk(f"due{i}", strength="due") for i in range(2)]
    unknown = [_risk(f"unk{i:02d}", strength="mystery") for i in range(10)]
    out = _cap_risks(due + unknown, MAX_RISKS_PER_LISTING)
    assert len(out) == 8
    assert [r.title for r in out if r.strength == "due"] == ["due0", "due1"]
    assert [r.title for r in out if r.strength == "mystery"] == [
        f"unk{i:02d}" for i in range(6)
    ]

    # Alone, unknown strengths are still capped — they never bypass the ceiling.
    only_unknown = [_risk(f"u{i}", strength="weird") for i in range(20)]
    assert len(_cap_risks(only_unknown, MAX_RISKS_PER_LISTING)) == MAX_RISKS_PER_LISTING


# ── Unit: boundary sizes the incident tests don't exercise ───────────────────

def test_exactly_cap_size_is_unchanged():
    """Exactly MAX_RISKS_PER_LISTING unprotected risks: nothing to trim, and the
    boundary (== n, not just > n or < n) must not off-by-one either direction.
    """
    risks = [_risk(f"r{i}") for i in range(MAX_RISKS_PER_LISTING)]
    out = _cap_risks(risks, MAX_RISKS_PER_LISTING)
    assert out == risks
    assert len(out) == MAX_RISKS_PER_LISTING


def test_empty_list_returns_empty():
    """No risks in → no risks out; the cap must not manufacture anything."""
    assert _cap_risks([], MAX_RISKS_PER_LISTING) == []


# ── End-to-end: /analyze must never serve more than the cap ──────────────────

def test_analyze_endpoint_caps_reported_claims_at_8(db, megane4_variants, monkeypatch, tmp_path):
    """The test that would have caught the production incident: seed >8 servable
    reported claims on one matched variant and drive the REAL serve path through
    /analyze. The response must carry exactly 8, and the serving sort must feed
    the cap the right ones (high-consequence kept over low).
    """
    # Keep the best-effort JSONL logger off the real logs/ file.
    monkeypatch.setattr(config, "ANALYSES_LOG_PATH", tmp_path / "analyses.jsonl")

    # 12 servable reported claims on megane4_k9k_90: 8 high-consequence, 4 low.
    # Each in its own domain so title-similarity dedup never merges them; medium
    # severity so the high-severity review gate doesn't withhold them.
    for i in range(12):
        consequence = "high" if i < 8 else "low"
        claim = Claim(
            id=f"cap_rep_{i}", claim_key=f"cap_rep_{i}", version=1, is_current=True,
            title=f"Reported subsystem {i} anomaly", domain=f"dom{i}",
            severity="medium", consequence=consequence, confidence=0.5,
            rationale="rationale", inspection_advice="advice",
            status="review", kind="known_issue",
        )
        db.add(claim)
        db.flush()
        db.add(ClaimVariant(claim_id=claim.id, variant_id="megane4_k9k_90", grounding_note="test"))
        db.add(ClaimSource(claim_id=claim.id, source_url="https://example.com", quote="q", independent=True))
    db.flush()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        client = TestClient(app)
        resp = client.post("/analyze", json={"ad_metadata": {
            "make": "Renault", "model": "Megane", "year": 2020, "fuel_type": "diesel",
            "engine_volume_cc": 1461, "power_hp": 90, "mileage_km": 50000,
        }})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["coverage_state"] == "risks_found"
    assert body["matched_variant_ids"] == ["megane4_k9k_90"]

    risks = body["risks"]
    assert len(risks) == MAX_RISKS_PER_LISTING  # capped — not the 12 that were servable
    assert all(r["strength"] == "reported" for r in risks)
    # The ranking fed the cap: the 8 high-consequence survived; all 4 low dropped.
    assert all(r["consequence"] == "high" for r in risks)
