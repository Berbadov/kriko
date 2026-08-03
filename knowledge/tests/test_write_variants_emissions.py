"""write_variants.build_rows — year-split emissions segments (B11).

A single variant row can't express a mid-life aftertreatment change (e.g. 1.5
dCi: LNT through 2018, then SCR). `emissions` on a trim may be a plain string
(one era, one row) or a list of year-bounded segments; each segment becomes its
own variant row with a suffixed id, so the SCR gate can ground per era instead
of guessing. Segments must fall inside the trim's own year window.
"""

import pytest

from knowledge.catalog.write_variants import _emissions_segments, build_rows

_SHARED = {"electrical_code": "meg4_elec", "body_code": "meg4_body"}


def _trim(**over):
    t = {
        "id": "meg4_k9k_110_edc", "generation": "IV", "engine_code": "K9K",
        "engine_family": "k9k_110", "fuel": "diesel", "displacement_cc": 1461,
        "power_min_hp": 110, "power_max_hp": 110, "transmission": "automatic",
        "transmission_code": "dc4", "year_from": 2016, "year_to": 2020,
        "notes": "1.5 dCi 110 EDC", "market": "TR",
    }
    t.update(over)
    return t


def test_single_string_emissions_keeps_one_row_and_id():
    rows = build_rows("renault", "megane_4", [_trim(emissions="euro6b")], _SHARED)
    assert len(rows) == 1
    assert rows[0]["id"] == "meg4_k9k_110_edc"
    assert rows[0]["emissions"] == "euro6b"
    assert rows[0]["aftertreatment"] == "lnt"
    assert rows[0]["year_from"] == 2016 and rows[0]["year_to"] == 2020


def test_no_emissions_emits_one_row_without_scr_fields():
    rows = build_rows("renault", "megane_4", [_trim()], _SHARED)
    assert len(rows) == 1
    assert "emissions" not in rows[0]
    assert "aftertreatment" not in rows[0]


def test_segments_emit_one_row_per_era_with_suffixed_ids():
    t = _trim(emissions=[
        {"year_from": 2016, "year_to": 2018, "emissions": "euro6b"},
        {"year_from": 2018, "year_to": 2020, "emissions": "euro6d_temp"},
    ])
    rows = build_rows("renault", "megane_4", [t], _SHARED)
    assert [r["id"] for r in rows] == [
        "meg4_k9k_110_edc__euro6b", "meg4_k9k_110_edc__euro6dtemp"]
    assert [r["aftertreatment"] for r in rows] == ["lnt", "scr"]
    assert [r["year_from"] for r in rows] == [2016, 2018]
    assert [r["year_to"] for r in rows] == [2018, 2020]


def test_segment_aftertreatment_override_wins():
    t = _trim(emissions=[
        {"year_from": 2016, "year_to": 2018, "emissions": "euro6b",
         "aftertreatment": "none"},
    ])
    rows = build_rows("renault", "megane_4", [t], _SHARED)
    assert rows[0]["aftertreatment"] == "none"


def test_segment_outside_trim_window_rejected():
    t = _trim(emissions=[
        {"year_from": 2021, "year_to": 2022, "emissions": "euro6d"},
    ])
    with pytest.raises(ValueError, match="outside the trim's own window"):
        _emissions_segments(t)


def test_segment_without_years_rejected():
    t = _trim(emissions=[{"year_from": 2016, "emissions": "euro6b"}])
    with pytest.raises(ValueError, match="need year_from and year_to"):
        _emissions_segments(t)


def test_segment_without_emissions_rejected():
    t = _trim(emissions=[{"year_from": 2016, "year_to": 2018}])
    with pytest.raises(ValueError, match="no emissions value"):
        _emissions_segments(t)
