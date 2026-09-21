"""Catalog doctor — identity damage is found and repaired for every car.

The doctor is the "already on disk" half of the identity mechanism: the write
gate stops new damage, this repairs what earlier paths wrote. It must be
idempotent (a second run changes nothing) and must never re-project fitment
from variant fields — the B16 swap deliberately remapped fitment onto the
merged part files, and re-projecting would silently point rows at part files
that no longer exist.
"""

import yaml

from packs.cars.pipeline.catalog import doctor


def _catalog(tmp_path, variants, fitment=None):
    (tmp_path / "variants").mkdir()
    (tmp_path / "fitment").mkdir()
    (tmp_path / "parts").mkdir()
    (tmp_path / "variants" / "volkswagen_golf_8.yaml").write_text(
        yaml.dump(variants, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if fitment is not None:
        (tmp_path / "fitment" / "volkswagen_golf_8.yaml").write_text(
            yaml.dump(fitment, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp_path


def _row(**kw):
    base = dict(id="impression_1_5_tsi_150", make="volkswagen", model="golf",
                generation=8, engine_code="1.5_TSI", engine_family="EA211_evo2",
                fuel="petrol", displacement_cc=1498, power_min_hp=150,
                power_max_hp=150, transmission="manual", transmission_code="6MT",
                electrical_code="", body_code="", year_from=2024, year_to=None,
                market="TR", notes="", drivetrain="fwd")
    base.update(kw)
    return base


def _kinds(findings):
    return {f.kind for f in findings}


def test_diagnose_finds_the_trim_shaped_lineup(tmp_path):
    data = _catalog(tmp_path, [_row(), _row(id="life_1_5_tsi_150")])
    kinds = _kinds(doctor.diagnose(data))
    assert {"noncanonical_code", "trim_shaped_id", "powertrain_duplicate"} <= kinds


def test_repair_merges_renames_and_normalizes(tmp_path):
    data = _catalog(tmp_path, [_row(), _row(id="life_1_5_tsi_150")])
    doctor.repair(data)
    rows = yaml.safe_load((data / "variants" / "volkswagen_golf_8.yaml").read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["id"] == "golf8_ea211evo2_150"
    assert rows[0]["engine_family"] == "ea211_evo2"
    assert rows[0]["transmission_code"] == "manual"


def test_repair_is_idempotent(tmp_path):
    data = _catalog(tmp_path, [_row(), _row(id="life_1_5_tsi_150")])
    doctor.repair(data)
    before = (data / "variants" / "volkswagen_golf_8.yaml").read_text(encoding="utf-8")
    second = doctor.repair(data)
    assert second.rewritten == []
    assert (data / "variants" / "volkswagen_golf_8.yaml").read_text(encoding="utf-8") == before


def test_unresearchable_code_fails_open_as_draft(tmp_path):
    """'7-speed DSG' names no unit — the row must not serve, and must be visible."""
    data = _catalog(tmp_path, [_row(transmission="automatic",
                                    transmission_code="7-speed DSG")])
    doctor.repair(data)
    rows = yaml.safe_load((data / "variants" / "volkswagen_golf_8.yaml").read_text(encoding="utf-8"))
    assert rows[0]["draft"] is True
    assert rows[0]["id"].endswith("_auto")
    remaining = doctor.diagnose(data)
    assert any(f.kind == "invalid_code" and not f.fixable for f in remaining)


def test_repair_preserves_a_remapped_fitment_row(tmp_path):
    """B16 regression: fitment points at merged part files, not variant fields."""
    data = _catalog(tmp_path, [_row(id="golf8_ea211evo2_150",
                                    engine_family="ea211_evo2",
                                    transmission_code="manual")],
                    fitment=[{"variant_id": "golf8_ea211evo2_150",
                              "engine_family": "ea211",   # merged part file
                              "transmission_code": "manual",
                              "electrical_code": "", "body_code": ""}])
    doctor.repair(data)
    rows = yaml.safe_load((data / "fitment" / "volkswagen_golf_8.yaml").read_text(encoding="utf-8"))
    assert rows[0]["engine_family"] == "ea211"


def test_repair_follows_renames_into_fitment_and_prunes_orphans(tmp_path):
    data = _catalog(tmp_path, [_row(), _row(id="life_1_5_tsi_150")],
                    fitment=[{"variant_id": "impression_1_5_tsi_150",
                              "engine_family": "ea211", "transmission_code": "manual",
                              "electrical_code": "", "body_code": ""},
                             {"variant_id": "life_1_5_tsi_150",
                              "engine_family": "ea211", "transmission_code": "manual",
                              "electrical_code": "", "body_code": ""}])
    doctor.repair(data)
    rows = yaml.safe_load((data / "fitment" / "volkswagen_golf_8.yaml").read_text(encoding="utf-8"))
    assert [r["variant_id"] for r in rows] == ["golf8_ea211evo2_150"]
    assert rows[0]["engine_family"] == "ea211"


def test_live_catalog_has_no_fixable_identity_damage():
    """CI gate: anything the doctor can fix must already be fixed on disk."""
    fixable = [f for f in doctor.diagnose() if f.fixable]
    assert fixable == [], "\n".join(f"[{f.kind}] {f.message}" for f in fixable)
