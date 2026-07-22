"""set_claim_mileage() — the pure mutation behind backfill_claim_mileage.py.

Sets applies_when.min_mileage_km on one claim (located by claim_key) without
disturbing its other applies_when keys (e.g. an existing year window). None
clears the bound so re-runs are idempotent.
"""

from knowledge.catalog.backfill_claim_mileage import set_claim_mileage


def _data(*claims):
    return {"part_id": "p", "part_type": "engine", "claims": list(claims)}


def test_sets_mileage_on_claim_without_applies_when():
    data = _data({"claim_key": "c1", "title": "x"})
    assert set_claim_mileage(data, "c1", 80000) is True
    assert data["claims"][0]["applies_when"]["min_mileage_km"] == 80000


def test_preserves_existing_year_window():
    data = _data({"claim_key": "c1", "title": "x",
                  "applies_when": {"applies_year_from": 2019}})
    set_claim_mileage(data, "c1", 60000)
    aw = data["claims"][0]["applies_when"]
    assert aw["applies_year_from"] == 2019  # untouched
    assert aw["min_mileage_km"] == 60000


def test_none_clears_the_bound():
    data = _data({"claim_key": "c1", "title": "x",
                  "applies_when": {"min_mileage_km": 80000}})
    set_claim_mileage(data, "c1", None)
    assert "min_mileage_km" not in data["claims"][0].get("applies_when", {})


def test_unknown_claim_key_returns_false():
    data = _data({"claim_key": "c1", "title": "x"})
    assert set_claim_mileage(data, "nope", 80000) is False
    assert "applies_when" not in data["claims"][0]


def test_targets_only_the_named_claim():
    data = _data({"claim_key": "c1", "title": "x"},
                 {"claim_key": "c2", "title": "y"})
    set_claim_mileage(data, "c2", 90000)
    assert "applies_when" not in data["claims"][0]
    assert data["claims"][1]["applies_when"]["min_mileage_km"] == 90000
