"""Sync populates the fields the serving rank/gates read from claim YAML.

Guards two things that had no test and so silently regressed once already:
- `consequence` is computed from the claim text at sync (feeds the serving rank);
- `applies_year_from/to` are read from applies_when in _upsert_part_claim (the
  part-YAML path) — previously only _upsert_claim_row set them, so part-claim
  year windows never reached the DB.

Phase 1 (source quality) adds source_tier/source_trust coverage below.
"""

from backend.sync import _upsert_part_claim


def _claim(**over):
    base = dict(
        claim_key="c1", title="Turbocharger failure",
        domain="engine", severity="medium", confidence=0.8,
        rationale="Turbo bearing wear and boost loss.",
        inspection_advice="Check boost.", status="review", kind="known_issue",
    )
    base.update(over)
    return base


def test_sync_computes_consequence_from_text(db):
    obj = _upsert_part_claim(db, "sync_conseq_high", _claim())
    assert obj.consequence == "high"  # "turbocharger" → high system


def test_sync_consequence_low_for_infotainment(db):
    obj = _upsert_part_claim(
        db, "sync_conseq_low",
        _claim(title="Infotainment freeze", rationale="head unit lags"))
    assert obj.consequence == "low"


def test_sync_reads_year_window_on_part_claim(db):
    obj = _upsert_part_claim(
        db, "sync_year_win",
        _claim(applies_when={"applies_year_from": 2019, "applies_year_to": 2022}))
    assert obj.applies_year_from == 2019
    assert obj.applies_year_to == 2022


# ── Phase 1: source tier/trust backfill ──────────────────────────────────────

def _src(domain, url=None):
    return {"source_domain": domain, "source_url": url or f"https://{domain}/x",
            "quote": "q", "independent": True}


def test_sync_source_tier_best_source_wins(db):
    """A claim with a specialist + a forum source is specialist-grade (max, not mean)."""
    obj = _upsert_part_claim(db, "sync_tier_best", _claim(
        sources=[_src("renaultforum.com"), _src("ecotorqueltd.wixsite.com")]))
    assert obj.source_tier == "specialist"
    assert obj.source_trust is not None and 0.0 < obj.source_trust <= 1.0


def test_sync_source_tier_null_without_sources(db):
    """Maintenance-style claims (no sources) stay trust-neutral, never penalised."""
    obj = _upsert_part_claim(db, "sync_tier_none", _claim(sources=[]))
    assert obj.source_tier is None
    assert obj.source_trust is None


def test_sync_source_tier_unknown_domain_is_default(db):
    """An unclassified domain lands on the registry default (seo_blog) — it must
    not inherit trust it hasn't earned."""
    obj = _upsert_part_claim(db, "sync_tier_unknown", _claim(
        sources=[_src("some-random-unclassified-site-xyz.org")]))
    assert obj.source_tier == "seo_blog"
    assert obj.source_trust is not None and obj.source_trust < 0.8

