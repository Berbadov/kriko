"""A 2B model on a CPU: code settles what it can see, the model what it cannot.

Measured on the recommended small model (tools/evaluate_local_pipeline.py,
fixed fictional evidence): it extracted exact, correct quotes and then marked
them "unclear" on identity and support, so a documented battery fault naming
the product word for word was thrown away. These rules only lift "unclear"
where the text shows the answer; "wrong" and "unsupported" still reject.
"""

from app.providers.local_identity import ProductIdentity, names_subject
from app.providers.local_pipeline import worded_in, similar_pairs

QUOTE = ("After eleven months, my Aster One ran for 14 minutes on its normal "
         "setting instead of the 45 minutes it delivered when new.")


def test_a_quote_that_names_the_product_settles_identity():
    identity = ProductIdentity(canonical_name="Aster One")
    assert names_subject(identity, QUOTE)
    assert not names_subject(identity, "A different vacuum ran for 14 minutes.")
    assert not names_subject(ProductIdentity(canonical_name=""), QUOTE)


def test_a_claim_in_the_quotes_own_words_is_supported():
    assert worded_in("Reduced Runtime on Normal Setting", QUOTE)
    assert worded_in("Shortened Battery Runtime",
                     "Two Aster One owners reported shortened battery runtime after a year of use.")
    assert not worded_in("Motor overheats", QUOTE)
    assert not worded_in("", QUOTE)


def test_two_reports_of_one_fault_are_put_to_the_pair_check():
    risks = [
        {"id": "a", "kind": "risk", "title": "Shortened Battery Runtime",
         "body": "Two owners reported shortened battery runtime after a year of use"},
        {"id": "b", "kind": "risk", "title": "Cracked dust-bin latches",
         "body": "Replaced cracked dust-bin latches on four Aster One units"},
        {"id": "c", "kind": "risk", "title": "Reduced Runtime on Normal Setting",
         "body": "Ran for 14 minutes instead of 45 minutes when new."},
    ]
    # Proposed, not merged: the model's pair check still decides.
    assert similar_pairs(risks, "Aster One") == [["a", "c"]]


def test_english_needs_no_rendering_into_english():
    from app.providers.local_pipeline import QuickLookPipeline

    assert QuickLookPipeline._already_in("en")
    assert QuickLookPipeline._already_in("en-GB")
    assert not QuickLookPipeline._already_in("tr")
