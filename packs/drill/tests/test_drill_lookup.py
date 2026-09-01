"""The same lookup path, driven over a category with nothing car-shaped in it.

`kriko/tests/test_lookup.py` proves the mechanism. This file proves the
mechanism is not secretly car-shaped: identical code, queried by brand and
model, gated on charge cycles and running hours, traversing battery platforms
instead of engine codes.

If the pivot fails, it fails here first.
"""

import pytest

from kriko.lookup import lookup
from kriko.lookup.query import Query
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    return build.build("packs/drill", tmp_path_factory.mktemp("dist") / "drill.kpack")


@pytest.fixture
def store(pack, tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, pack)
    yield conn
    conn.close()


def _titles(result):
    return [c.title for c in result.claims]


def test_a_drill_resolves_by_brand_and_model(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "makita", "model": "DHP484"}))
    assert result.resolution.method == "exact"


def test_the_engine_never_sees_a_car_word(store):
    """The query that works here contains no make, model-year, fuel or mileage."""
    result = lookup(store, Query(
        kind="product",
        identity={"brand": "makita", "model": "DHP484"},
        context={"charge_cycles": 900, "usage_hours": 600}))
    assert result.coverage == "RISKS_FOUND"


def test_a_platform_claim_reaches_the_tool_through_part_of(store):
    """Structurally the same traversal as an engine-code claim reaching a car."""
    result = lookup(store, Query(
        kind="product",
        identity={"brand": "makita", "model": "DHP484"},
        context={"charge_cycles": 900}))
    titles = _titles(result)
    assert "Cell imbalance trips the pack protection early" in titles
    claim = next(c for c in result.claims if c.title.startswith("Cell imbalance"))
    assert claim.via.startswith("part_of:")


def test_charge_cycles_gate_the_battery_claim(store):
    """Wear in cycles, not kilometres — and the engine has no opinion about it."""
    low = lookup(store, Query(kind="product",
                              identity={"brand": "makita", "model": "DHP484"},
                              context={"charge_cycles": 50}))
    high = lookup(store, Query(kind="product",
                               identity={"brand": "makita", "model": "DHP484"},
                               context={"charge_cycles": 900}))
    assert "Cell imbalance trips the pack protection early" not in _titles(low)
    assert "Cell imbalance trips the pack protection early" in _titles(high)


def test_an_unstated_cycle_count_still_surfaces_the_claim(store):
    """Fail open: a buyer who cannot count cycles must still be warned."""
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "makita", "model": "DHP484"}))
    claim = next(c for c in result.claims if c.title.startswith("Cell imbalance"))
    assert "charge_cycles" in " ".join(claim.why)


def test_the_contradicted_battery_claim_still_shows_with_its_rebuttal(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "makita", "model": "DHP484"},
                                 context={"charge_cycles": 900}))
    claim = next(c for c in result.claims if c.title.startswith("Cell imbalance"))
    assert claim.disputed is True
    assert any(s.stance == "refutes" for s in claim.sources)
    assert any("contradicted" in reason for reason in claim.why)


def test_the_drill_with_no_components_answers_from_its_own_claims(store):
    """Zero relations. This must work without the engine branching on it."""
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "einhell", "model": "TC-CD-18-2"},
                                 context={"age_years": 5}))
    assert result.resolution.method == "exact"
    assert _titles(result) == ["Gearbox selector sticks between speed settings"]


def test_brushed_and_brushless_siblings_get_different_claims(store):
    """DHP482 has the brush-service item; the brushless DHP484 must not."""
    brushed = _titles(lookup(store, Query(
        kind="product", identity={"brand": "makita", "model": "DHP482"},
        context={"usage_hours": 900})))
    brushless = _titles(lookup(store, Query(
        kind="product", identity={"brand": "makita", "model": "DHP484"},
        context={"usage_hours": 900})))
    assert any("brush replacement" in t for t in brushed)
    assert not any("brush replacement" in t for t in brushless)


def test_turkish_text_comes_back_when_asked_for(store):
    """Language is a row, so a pack may carry any number of them."""
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "makita", "model": "DHP484"},
                                 context={"charge_cycles": 900}, lang="tr"))
    claim = next(c for c in result.claims if c.subject_label.startswith("Makita LXT"))
    assert claim.title.startswith("Hücre dengesizliği")


def test_an_unknown_drill_is_no_match(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "makita", "model": "NOPE"}))
    assert result.resolution.method == "no_match"
    assert result.coverage == "NOT_MATCHED"
