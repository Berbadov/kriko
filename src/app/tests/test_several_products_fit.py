"""A page that names a model but not its variant fits several products.

The lookup serves only what every candidate shares, so such a page could come
back with nothing while the pack knew a great deal about each variant, and the
panel told the reader that was "a gap, not a clean bill of health". It is a
question for the reader, and the answer asks it.
"""

from app import matching
from kriko.lookup.query import Resolution

SUBJECTS = [{"subject_id": f"s{i}", "label": f"Variant {i}", "pack_id": "p", "kind": "product",
             "claims": 0} for i in range(9)]


def _several(n=9):
    return Resolution(tuple(f"s{i}" for i in range(n)), "ambiguous")


def test_several_fitting_products_are_not_called_recognised():
    assert matching.verdict(_several()) == "several"
    assert matching.verdict(Resolution(("s0",), "exact")) == "recognised"


def test_nothing_shared_asks_which_one_instead_of_calling_it_a_gap():
    step = matching.next_step(_several(), "MATCHED_NO_DATA", "", SUBJECTS)
    assert step["action"] == "choose"
    assert "gap" not in step["say"]
    assert "9 products" in step["say"]
    assert [one["label"] for one in step["choices"]] == [f"Variant {i}" for i in range(matching.MAX_CHOICES)]


def test_shared_claims_still_offer_the_narrower_answer():
    step = matching.next_step(_several(2), "RISKS_FOUND", "", SUBJECTS[:2])
    assert step["action"] == "choose"
    assert "only what all of them share" in step["say"]


def test_an_exact_match_with_nothing_known_is_still_a_gap():
    step = matching.next_step(Resolution(("s0",), "exact"), "MATCHED_NO_DATA", "", SUBJECTS[:1])
    assert step["action"] == "research"
    assert "gap" in step["say"]


def test_two_products_labelled_alike_are_one_choice():
    twins = [{"subject_id": "a", "label": "Same"}, {"subject_id": "b", "label": "Same"},
             {"subject_id": "c", "label": "Other"}]
    step = matching.next_step(_several(3), "MATCHED_NO_DATA", "", twins)
    assert [one["label"] for one in step["choices"]] == ["Same", "Other"]
