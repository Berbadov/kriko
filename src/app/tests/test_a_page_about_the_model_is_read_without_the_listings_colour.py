"""A page about the phone is read even though it never says the colour.

The reader's quick look on a price-comparison listing ("Samsung Galaxy A54 256 GB
Beyaz") opened a review of the Samsung Galaxy A54 5G and threw it away as "without
an exact product match", because the listing's storage size and colour are not on
a review's page. The page was about the product; only the whole title was absent.
"""

from app.providers.local_identity import ProductIdentity, relevant_source

NAME = "Samsung Galaxy A54 256 GB Beyaz"


def _identity(name=NAME) -> ProductIdentity:
    return ProductIdentity(canonical_name=name, stated=())


def test_a_review_of_the_model_counts_without_the_storage_size_and_colour():
    page = "Samsung Galaxy A54 5G review: the affordable mid-ranger with a big battery."
    assert relevant_source(_identity(), "Samsung Galaxy A54 5G", page)


def test_a_page_about_another_model_still_does_not_count():
    page = "Samsung Galaxy A34 review: a cheaper phone with a smaller screen."
    assert not relevant_source(_identity(), "Samsung Galaxy A34", page)


def test_the_model_code_alone_on_an_unrelated_page_does_not_count():
    # A54 is also a road, a motorway junction, a part number: another word of
    # the name has to be on the page with it.
    page = "Closure of the A54 between junctions 3 and 4 for resurfacing this weekend."
    assert not relevant_source(_identity(), "Roadworks", page)
