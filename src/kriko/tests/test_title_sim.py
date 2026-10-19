"""Two titles are one claim only when they name the same thing.

Read-time title clustering *is* the deduplication a reader experiences — claim
ids rarely collide, because three language models write three titles for one
failure. It was also the one mechanism in the engine with no test of its own,
and it had two defects:

* the ledger's authoring-time tokeniser dropped every digit, so "E90 timing
  chain" and "E91 timing chain" were one cluster there and two here;
* word overlap alone cannot separate them anyway — they share every word but
  the part number, which scores 0.5 against a 0.4 threshold. A disagreement
  about an identifier now vetoes the merge, and only when *both* titles carry
  one, so a title that merely omits a detail is not split off from the one that
  includes it.
"""

from kriko.ledger.cluster import jaccard
from kriko.text.title_sim import similarity, title_similar


def test_two_part_numbers_are_not_a_duplicate():
    assert not title_similar("E90 timing chain", "E91 timing chain")
    assert not title_similar("Bosch GBH 2-26 chuck slips", "Bosch GBH 2-24 chuck slips")


def test_two_quantities_are_not_a_duplicate():
    """A lone digit is an identifier too, and the tokeniser drops it."""
    assert not title_similar("fails after 3 months", "fails after 5 months")


def test_a_shared_identifier_still_merges_one_claim_said_twice():
    assert title_similar(
        "E90 timing chain fails at 60000 miles", "E90 timing chain failure")
    assert title_similar("fails after 3 months", "fails after 3 to 5 months")


def test_a_title_that_only_omits_a_detail_is_not_split_off():
    assert title_similar(
        "1.6 TDI injector failure", "1.6 TDI injector failure on cold start")


def test_a_reworded_title_with_no_number_still_merges():
    assert title_similar(
        "screen flicker at low brightness", "screen flickering at low brightness")


def test_an_unrelated_title_is_not_a_duplicate():
    assert not title_similar("brake pad wear", "screen flicker")


def test_the_identifier_rule_is_what_separates_them():
    """Not the threshold: the words alone score 0.5, over the 0.4 line."""
    assert similarity("E90 timing chain", "E91 timing chain") == 0.0


def test_the_authoring_ledger_and_a_lookup_agree_on_a_duplicate():
    """One tokeniser, two callers. Their disagreement was the defect."""
    for one, other in (
        ("E90 timing chain", "E91 timing chain"),
        ("E90 timing chain", "E90 timing chain stretched"),
        ("brake pad wear", "screen flicker"),
    ):
        assert jaccard(one, other) == similarity(one, other)
