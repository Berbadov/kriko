"""Seller and quote risk, and the landed-cost order of quotes.

Every case is a quote a reader could type: a named retailer, a marketplace
that does not name its seller, a classified ad, an expired offer. None of these
functions touches the network, so the test is the whole authority on the
sentence a screen will show.
"""

from datetime import date

from app.quoterisk import quote_risk, rank_quotes

TODAY = date(2026, 11, 20)


def test_a_known_retailer_is_green_and_says_which_site():
    risk = quote_risk({"url": "https://www.mediamarkt.de/p/1", "seller": "MediaMarkt"}, today=TODAY)
    assert risk["level"] == "green"
    assert any("mediamarkt" in reason for reason in risk["reasons"])


def test_a_marketplace_without_a_seller_is_amber_and_never_trusted():
    risk = quote_risk({"url": "https://www.amazon.de/dp/x"}, today=TODAY)
    assert risk["level"] == "amber"
    assert any("marketplace" in reason for reason in risk["reasons"])
    assert any("not named" in reason for reason in risk["reasons"])


def test_a_classified_ad_is_red_and_an_unknown_domain_is_not_green():
    classified = quote_risk({"url": "https://www.sahibinden.com/ilan/1"}, today=TODAY)
    assert classified["level"] == "red"
    unknown = quote_risk({"url": "https://shop.nobody-has-heard-of.example/p"}, today=TODAY)
    assert unknown["level"] == "unknown", "an unrecognised site has not earned a favourable mark"


def test_no_url_is_unknown_and_says_so():
    risk = quote_risk({"vendor": "A man at the market"}, today=TODAY)
    assert risk["level"] == "unknown"
    assert risk["site"] is None


def test_an_expired_quote_and_a_long_delivery_are_reasons_never_silent():
    risk = quote_risk({
        "url": "https://www.mediamarkt.de/p/1", "seller": "MediaMarkt",
        "delivery_days": 90, "valid_until": "2026-10-01",
    }, today=TODAY)
    assert risk["level"] == "amber"
    assert any("expired on 2026-10-01" in reason for reason in risk["reasons"])
    assert any("90 days" in reason for reason in risk["reasons"])


def test_landed_cost_compares_gross_prices_at_the_stated_rate():
    quotes = [
        {"quote_id": "eur", "unit_price": 100, "currency": "EUR", "vat_rate": 20,
         "vat_included": False, "delivery_days": 10},
        {"quote_id": "try", "unit_price": 3000, "currency": "TRY", "vat_rate": 20,
         "vat_included": True, "delivery_days": 5},
    ]
    ranked = rank_quotes(quotes, estimate_currency="TRY",
                         rates={"TRY": 1.0, "EUR": 35.0, "USD": 32.0}, today=TODAY)
    assert [row["quote_id"] for row in ranked] == ["try", "eur"]
    assert ranked[1]["landed"] == 4200.0  # 100 + 20% VAT, at 35 TRY
    assert ranked[1]["rank"] == 2
    assert ranked[1]["rank_reasons"][0].startswith("120.00 EUR gross")


def test_a_currency_with_no_rate_is_not_ranked_and_says_why():
    ranked = rank_quotes(
        [{"quote_id": "gbp", "unit_price": 10, "currency": "GBP"}],
        estimate_currency="TRY", rates={"TRY": 1.0}, today=TODAY)
    assert ranked[0]["landed"] is None
    assert ranked[0]["rank"] is None
    assert any("no GBP to TRY rate" in reason for reason in ranked[0]["rank_reasons"])


def test_a_gross_quote_is_ranked_at_the_price_typed():
    ranked = rank_quotes(
        [{"quote_id": "gross", "unit_price": 120, "currency": "TRY",
          "vat_rate": 20, "vat_included": True}],
        estimate_currency="TRY", rates={"TRY": 1.0}, today=TODAY)
    assert ranked[0]["landed"] == 120.0


def test_the_same_quotes_always_rank_the_same_way():
    quotes = [
        {"quote_id": "b", "unit_price": 10, "currency": "TRY", "vat_included": True,
         "delivery_days": 3},
        {"quote_id": "a", "unit_price": 10, "currency": "TRY", "vat_included": True,
         "delivery_days": 3},
    ]
    first = rank_quotes(quotes, estimate_currency="TRY", rates={"TRY": 1.0}, today=TODAY)
    second = rank_quotes(list(reversed(quotes)), estimate_currency="TRY",
                         rates={"TRY": 1.0}, today=TODAY)
    assert [row["quote_id"] for row in first] == [row["quote_id"] for row in second]
