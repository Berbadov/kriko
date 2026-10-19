"""The seller, the score and the big words, checked against what the page shows."""

import pytest

from app import audit


def test_a_score_from_a_handful_of_people_is_pulled_toward_ordinary():
    few = audit.reviews({"ld:ratingValue": "4.9", "ld:reviewCount": "7"})
    many = audit.reviews({"ld:ratingValue": "4.6", "ld:reviewCount": "9000"})
    assert few["doubtful"] and "mostly noise" in few["notes"][0]
    assert few["adjusted"] < 4.4 < many["adjusted"] <= 4.6
    assert not many["doubtful"]


def test_a_flawless_score_from_many_people_is_named_rare():
    got = audit.reviews({"ld:ratingValue": "5", "ld:reviewCount": "400"})
    assert got["doubtful"] and "rare" in got["notes"][0]


def test_a_score_with_no_count_and_a_zero_count_are_both_doubtful():
    assert "not how many" in audit.reviews({"ld:ratingValue": "4.8"})["notes"][0]
    assert "zero ratings" in " ".join(audit.reviews({"ld:ratingValue": "5", "ld:reviewCount": "0"})["notes"])


def test_a_rating_on_another_scale_is_put_on_five():
    got = audit.reviews({"ld:ratingValue": "9", "ld:bestRating": "10", "ld:reviewCount": "500"})
    assert got["stars"] == 4.5


@pytest.mark.parametrize("fields", [{}, {"ld:ratingValue": "abc"}, {"ld:ratingValue": "9"},
                                    {"ld:ratingValue": "4", "ld:bestRating": "0"}])
def test_no_usable_rating_is_no_review_block(fields):
    assert audit.reviews(fields) == {}


def test_a_marketplace_listing_that_names_no_seller_is_amber_and_a_scam_payment_is_red():
    quiet = audit.seller("https://www.amazon.com/dp/1", {}, "Great kettle")
    assert quiet["site"]["tier"] == "marketplace" and quiet["level"] == "amber"
    named = audit.seller("https://www.amazon.com/dp/1", {"ld:seller": "Kettle Co"}, "")
    assert named["level"] == "green" and named["signals"]["seller_name"] == "Kettle Co"
    scam = audit.seller("https://shop.example/p", {}, "We only accept bitcoin or Western Union")
    assert scam["level"] == "red" and "payment" in " ".join(scam["notes"])


def test_an_official_line_on_a_marketplace_is_not_proof():
    got = audit.seller("https://www.amazon.com/dp/1", {"ld:seller": "X"},
                       "Authorised dealer of the brand")
    assert any("anyone can say that" in note for note in got["notes"])


def test_water_resistance_is_backed_only_by_a_rating_on_the_page():
    unbacked = audit.claims("Waterproof speaker", "", {"Weight": "400 g"})
    backed = audit.claims("Waterproof speaker", "", {"Water resistance": "IP67"})
    assert unbacked["items"][0]["status"] == "unbacked"
    assert "IP code" in unbacked["items"][0]["why"]
    assert backed["items"][0]["status"] == "backed" and backed["meter"] == 100


def test_original_is_the_sellers_word_unless_the_seller_is_authorised_off_a_marketplace():
    marketplace = audit.seller("https://www.hepsiburada.com/x", {}, "")
    got = audit.claims("%100 Orijinal şarj aleti", "", {}, marketplace)
    assert got["items"][0]["kind"] == "authentic" and got["items"][0]["status"] == "seller_word"
    brand = audit.seller("https://www.teknosa.com/x", {}, "Authorised dealer")
    assert audit.claims("Original charger", "", {}, brand)["items"][0]["status"] == "backed"


def test_a_superlative_is_puffery_and_does_not_enter_the_meter():
    got = audit.claims("The best kettle ever", "", {})
    assert got["items"][0]["status"] == "puffery" and got["meter"] is None
    assert got["unbacked"] == 0


def test_the_meter_is_the_share_of_checkable_claims_that_are_backed():
    got = audit.claims("Waterproof, certified, 2 year warranty", "", {
        "Water resistance": "IP68", "Warranty": "2 years"})
    kinds = {one["kind"]: one["status"] for one in got["items"]}
    assert kinds == {"water": "backed", "warranty": "backed", "certified": "unbacked"}
    assert got["meter"] == 67 and got["unbacked"] == 1


def test_turkish_claim_words_are_read():
    got = audit.claims("Su geçirmez kulaklık, sertifikalı, en iyi", "", {})
    assert {one["kind"] for one in got["items"]} == {"water", "certified", "best"}


def test_a_listing_leads_with_the_worst_thing_and_says_nothing_when_all_is_well():
    bad = audit.listing(url="https://shop.example/p", title="Waterproof speaker",
                        description="pay by bitcoin",
                        fields={"ld:ratingValue": "5", "ld:reviewCount": "3"})
    assert bad["headline"].startswith("Seller:") and len(bad["flags"]) == 3
    good = audit.listing(url="https://www.amazon.com/dp/1", title="Kettle",
                         fields={"ld:seller": "Kettle Co", "ld:ratingValue": "4.5",
                                 "ld:reviewCount": "900"})
    assert good["headline"] == "" and good["flags"] == []
