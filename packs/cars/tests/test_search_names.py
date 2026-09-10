"""What a person would type, as against what a list needs to show.

The defect this file exists for was reported twice and looked like an engine
fault both times: every query in the brief read

    Volkswagen Golf 1.5_TSI 150 hp common problems

and the reader said "queries are still fucked up". Nothing in the engine was
wrong. `_label` is a *display* string — it carries the raw engine code and the
power floor precisely so two variants of one model can be told apart in a list
— and it was the only string a query template had to substitute. One string
doing two jobs.

So the pack now ships the other job as data: `search_name` aliases, whole
phrases somebody would type. These tests hold the shape of those phrases,
because the failure mode is not an exception — it is a query that runs and
finds nothing.
"""

from packs.cars.build import _search_names

VARIANT = {
    "make": "volkswagen",
    "model": "golf",
    "engine_code": "1.5_TSI",
    "generation": "Mk7.5",
    "power_hp": 150,
}


def test_a_search_name_is_a_phrase_somebody_would_type():
    names = _search_names(VARIANT)
    assert "Volkswagen Golf 1.5 TSI" in names
    # The underscore is a catalog spelling, not a word. Nobody searches for it.
    assert not any("_" in name for name in names)
    # And the power floor is a disambiguator for a list, not a search term:
    # "150 hp" in a query is what made every one of the seven find nothing.
    assert not any("hp" in name.lower() for name in names)


def test_the_plain_make_and_model_is_offered_too():
    """Forums thread by model, not by engine code. Both shapes, widest last."""
    names = _search_names(VARIANT)
    assert names[-1] == "Volkswagen Golf"
    assert names.index("Volkswagen Golf 1.5 TSI") < names.index("Volkswagen Golf")


def test_a_variant_missing_its_model_offers_nothing_rather_than_a_fragment():
    """`Volkswagen  problems` is a query that runs and cannot succeed."""
    assert _search_names({"make": "volkswagen"}) == []
    assert _search_names({}) == []


def test_the_same_phrase_is_never_offered_twice():
    """One query per name, and a duplicate name is a duplicate search."""
    names = _search_names({"make": "bmw", "model": "320i"})
    assert names == sorted(set(names), key=names.index)
