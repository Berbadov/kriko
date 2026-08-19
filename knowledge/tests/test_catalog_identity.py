"""Variant identity rules — the gate that stops trim-shaped lineups.

Regression origin: an agent onboarding of VW Golf 8 submitted four marketing
trims (Impression/Life/Style/R-Line) describing two powertrains. submit_trims
said OK; CI failed later. These tests pin the rule at the write path.
"""

from knowledge.catalog import identity


def _row(**kw) -> dict:
    base = dict(id="x", make="volkswagen", model="golf", fuel="petrol",
                engine_family="ea211", transmission="manual",
                transmission_code="manual", displacement_cc=1498,
                power_min_hp=150, power_max_hp=150, year_from=2024,
                year_to=None, generation=8)
    base.update(kw)
    return base


# ── code vocabulary ──────────────────────────────────────────────────────────

def test_canonical_code_normalizes_to_catalog_form():
    assert identity.canonical_code("7-speed DSG") == "7_speed_dsg"
    assert identity.canonical_code("EA211_evo2") == "ea211_evo2"
    assert identity.canonical_code("  DQ381 ") == "dq381"


def test_description_shaped_transmission_code_is_rejected():
    errs = identity.code_errors("transmission_code", "7_speed_dsg", "automatic")
    assert errs and "unit code" in errs[0]


def test_shared_technology_descriptor_is_rejected():
    """'DSG' names three different gearboxes — attributing to it contaminates."""
    errs = identity.code_errors("transmission_code", "dsg", "automatic")
    assert errs and "sibling" in errs[0].lower() or "contaminate" in errs[0]


def test_real_unit_codes_pass():
    assert identity.code_errors("transmission_code", "dq381", "automatic") == []
    assert identity.code_errors("engine_family", "ea211_evo2") == []
    assert identity.code_errors("engine_family", "h5h_130") == []


def test_manual_boxes_are_never_rejected():
    assert identity.code_errors("transmission_code", "6mt", "manual") == []
    assert identity.code_errors("transmission_code", "manual", "manual") == []
    assert identity.is_manualish("6MT") and identity.is_manualish("5_speed_manual")


def test_known_part_codes_are_read_off_the_catalog(tmp_path):
    (tmp_path / "parts" / "engine").mkdir(parents=True)
    (tmp_path / "parts" / "engine" / "ea888.yaml").write_text("part_id: ea888\n")
    assert identity.known_part_codes(tmp_path) == {"ea888"}


# ── powertrain identity ──────────────────────────────────────────────────────

def test_trim_shaped_rows_are_indistinguishable():
    a, b = _row(id="impression_1_5_tsi_150"), _row(id="life_1_5_tsi_150")
    assert identity.indistinguishable(a, b)
    assert identity.find_overlaps([a, b])


def test_transmission_split_resolves_a_cc_power_collision():
    a = _row(id="a", transmission="manual", transmission_code="manual")
    b = _row(id="b", transmission="automatic", transmission_code="dq381")
    assert not identity.indistinguishable(a, b)
    assert identity.find_overlaps([a, b]) == []


def test_non_overlapping_years_are_not_a_collision():
    a = _row(id="a", year_from=2015, year_to=2018)
    b = _row(id="b", year_from=2019, year_to=None)
    assert identity.find_overlaps([a, b]) == []


def test_collapse_merges_same_powertrain_and_reports_it():
    rows = [_row(id="impression", power_min_hp=150, power_max_hp=150,
                 year_from=2024, year_to=2025),
            _row(id="life", power_min_hp=150, power_max_hp=150,
                 year_from=2020, year_to=None)]
    merged, notes = identity.collapse_duplicates(rows)
    assert len(merged) == 1
    assert merged[0]["id"] == "impression"
    assert merged[0]["year_from"] == 2020 and merged[0]["year_to"] is None
    assert notes and "same powertrain" in notes[0]


def test_collapse_keeps_different_gearboxes_apart():
    rows = [_row(id="a", transmission="automatic", transmission_code="dq200"),
            _row(id="b", transmission="automatic", transmission_code="dq381")]
    merged, notes = identity.collapse_duplicates(rows)
    assert len(merged) == 2 and notes == []


def test_collapse_keeps_a_draft_flag_when_either_side_is_draft():
    rows = [_row(id="a"), _row(id="b", draft=True)]
    merged, _ = identity.collapse_duplicates(rows)
    assert merged[0]["draft"] is True


def test_canonical_variant_id_is_derived_from_the_powertrain():
    row = _row(engine_family="EA211_evo2", power_max_hp=150,
               transmission="automatic", transmission_code="dq381")
    assert identity.canonical_variant_id("volkswagen_golf_8", row) == \
        "golf8_ea211evo2_150_dq381"


def test_canonical_variant_id_omits_the_gearbox_for_manuals():
    assert identity.canonical_variant_id("volkswagen_golf_8", _row()) == \
        "golf8_ea211_150"


def test_catalog_on_disk_has_no_unresolvable_overlaps():
    """Same assertion backend/tests/test_catalog.py makes — one rule, two callers."""
    import yaml
    rows = []
    for path in sorted((identity.DATA_DIR / "variants").glob("*.yaml")):
        rows.extend(yaml.safe_load(path.read_text()) or [])
    assert identity.find_overlaps(rows) == []
