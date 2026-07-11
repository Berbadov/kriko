"""set_claim_window() — the pure mutation behind backfill_claim_window.py.

Sets an applies_when.applies_year_from/to model-year window on one claim,
located inside a part file's claims list by claim_key, without disturbing the
claim's other applies_when keys. Returns whether the claim was found.
"""

from knowledge.catalog.backfill_claim_window import set_claim_window


def _data(*claims):
    return {"part_id": "p", "part_type": "engine", "claims": list(claims)}


def test_sets_window_on_claim_without_applies_when():
    data = _data({"claim_key": "c1", "title": "x"})
    found = set_claim_window(data, "c1", 2019, 2022)
    assert found is True
    aw = data["claims"][0]["applies_when"]
    assert aw["applies_year_from"] == 2019
    assert aw["applies_year_to"] == 2022


def test_preserves_existing_applies_when_keys():
    data = _data({"claim_key": "c1", "title": "x", "applies_when": {"min_mileage_km": 80000}})
    set_claim_window(data, "c1", 2019, 2022)
    aw = data["claims"][0]["applies_when"]
    assert aw["min_mileage_km"] == 80000  # untouched
    assert aw["applies_year_from"] == 2019
    assert aw["applies_year_to"] == 2022


def test_open_ended_upper_bound_is_omitted_not_null():
    data = _data({"claim_key": "c1", "title": "x"})
    set_claim_window(data, "c1", 2023, None)
    aw = data["claims"][0]["applies_when"]
    assert aw["applies_year_from"] == 2023
    assert "applies_year_to" not in aw  # None → omit, so the gate reads it as open-ended


def test_none_lower_bound_clears_existing_bound():
    data = _data({"claim_key": "c1", "title": "x", "applies_when": {"applies_year_from": 2019}})
    set_claim_window(data, "c1", None, None)
    aw = data["claims"][0].get("applies_when", {})
    assert "applies_year_from" not in aw  # cleared, idempotent re-run support


def test_unknown_claim_key_returns_false_and_no_mutation():
    data = _data({"claim_key": "c1", "title": "x"})
    found = set_claim_window(data, "does_not_exist", 2019, 2022)
    assert found is False
    assert "applies_when" not in data["claims"][0]


def test_targets_only_the_named_claim():
    data = _data(
        {"claim_key": "c1", "title": "x"},
        {"claim_key": "c2", "title": "y"},
    )
    set_claim_window(data, "c2", 2020, 2021)
    assert "applies_when" not in data["claims"][0]
    assert data["claims"][1]["applies_when"]["applies_year_from"] == 2020
