"""Sync populates the fields the serving rank/gates read from claim YAML.

Guards two things that had no test and so silently regressed once already:
- `consequence` is computed from the claim text at sync (feeds the serving rank);
- `applies_year_from/to` are read from applies_when in _upsert_part_claim (the
  part-YAML path) — previously only _upsert_claim_row set them, so part-claim
  year windows never reached the DB.
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
