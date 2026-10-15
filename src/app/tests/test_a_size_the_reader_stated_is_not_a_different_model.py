"""A page that says the model and then a size the reader's own title says is
about this product.

`conflicting_identity` read any bare number or mixed token after the model name
as a neighbouring version, so a page titled "<model> 500GB SSD Review" for a
listing titled "<model> 500 GB" had every candidate refused (the Samsung 870
EVO run: five rejections a page, 0 findings, nothing wrong with the evidence).
"""

from app.providers.local_identity import (
    ProductIdentity, conflicting_identity, parse_identity, stated_tokens,
)

TITLE = "Samsung 870 EVO MZ-77E500BW SATA 2.5 inch 500 GB SSD"
NAME = "Samsung 870 EVO MZ-77E500BW"


def identity(title=TITLE):
    return ProductIdentity(canonical_name=NAME, stated=stated_tokens(title))


def test_a_size_the_title_states_is_not_a_conflict_however_the_page_spells_it():
    for page in (f"{NAME} 500GB SSD Review: Performance",
                 f"{NAME} 500 GB UA | E-Catalog",
                 f"{NAME} 2.5 inch drive failed after a week"):
        assert not conflicting_identity(identity(), page), page


def test_a_size_the_title_does_not_state_is_still_a_different_version():
    assert conflicting_identity(identity(), f"{NAME} 1TB SSD Review")
    assert conflicting_identity(identity(), f"{NAME} 250 GB model failed")


def test_a_modifier_is_a_conflict_even_when_the_title_has_a_similar_word():
    # whole tokens only: "improved" in a title must not excuse "pro".
    assert conflicting_identity(identity(TITLE + " improved"), f"{NAME} Pro review")


def test_an_identity_parsed_from_a_reply_keeps_the_title_it_was_asked_about():
    parsed = parse_identity("not json", TITLE)
    assert not conflicting_identity(parsed, f"{NAME} 500GB review")
