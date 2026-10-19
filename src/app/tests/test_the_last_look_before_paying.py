"""The checkout guard: a wrong variant, a cheaper shop, a scam payment, a page with no returns."""

from datetime import UTC, datetime, timedelta

import pytest

from app import checkout, pricewatch
from app.web import state

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


@pytest.mark.parametrize("url,expected", [
    ("https://shop.test/cart", True), ("https://shop.test/checkout/payment", True),
    ("https://shop.test/sepet", True), ("https://shop.test/odeme?x=1", True),
    ("https://shop.test/warenkorb/", True), ("https://shop.test/p/cartridge-12", False),
    ("https://shop.test/p/kettle", False),
])
def test_a_checkout_page_is_known_by_what_its_address_says(url, expected):
    assert checkout.is_checkout(url) is expected


def test_the_same_family_with_other_numbers_clashes_and_another_colour_does_not():
    assert checkout.variant_clash("Phone X 128GB", "Phone X 256GB")
    assert not checkout.variant_clash("Phone X blue", "Phone X black")
    assert not checkout.variant_clash("Phone X 128GB", "Garden hose 25m")


def research(conn, name):
    conn.execute("INSERT INTO lookups (lookup_id, created_at, source, label, request_json, response_json)"
                 " VALUES (?, ?, 'extension', ?, '{}', '{}')",
                 (name, NOW.isoformat(), name))
    conn.commit()


def test_a_wrong_variant_in_the_cart_stops_the_reader(conn):
    research(conn, "Phone X 256GB")
    got = checkout.guard(conn, url="https://shop.test/cart", text="Returns within 14 days",
                         items=[{"name": "Phone X 128GB", "price": "500"}], now=NOW)
    assert got["verdict"] == "stop"
    assert "researched “Phone X 256GB”" in got["headline"]


def test_the_item_researched_is_not_a_clash_with_itself(conn):
    research(conn, "Phone X 256GB")
    got = checkout.guard(conn, url="https://shop.test/cart", text="Return policy",
                         items=[{"name": "Phone X 256GB", "price": "500"}], now=NOW)
    assert got["verdict"] == "go"


def test_a_cheaper_shop_is_named_with_its_price(conn):
    pricewatch.record(conn, "https://other.test/p/9", "Sony WH-1000XM5", {"price": 270, "currency": "EUR"},
                      now=NOW - timedelta(days=3))
    got = checkout.guard(conn, url="https://shop.test/cart", text="30 day returns",
                         items=[{"name": "Sony WH-1000XM5", "price": 300, "currency": "EUR",
                                 "url": "https://shop.test/p/1"}], now=NOW)
    assert got["verdict"] == "check"
    assert "270 EUR on other.test (you pay 300)" in got["headline"]


def test_a_scam_payment_method_is_a_stop(conn):
    got = checkout.guard(conn, url="https://shop.example/checkout", text="We accept Western Union only. Returns: none",
                         items=[{"name": "Thing", "price": 10}], now=NOW)
    assert got["verdict"] == "stop" and got["seller"] == "red"


def test_a_page_that_shows_no_return_terms_says_check_not_no_returns(conn):
    got = checkout.guard(conn, url="https://www.teknosa.com/sepet", text="Pay now",
                         items=[{"name": "Thing", "price": 10}], now=NOW)
    assert got["verdict"] == "check"
    assert "shows no return terms" in got["headline"]


def test_with_no_cart_lines_the_recent_views_on_that_shop_stand_in(conn):
    pricewatch.record(conn, "https://shop.test/p/1", "Kettle X200", {"price": 40, "currency": "EUR"},
                      now=NOW - timedelta(hours=2))
    pricewatch.record(conn, "https://shop.test/p/2", "Old", {"price": 9, "currency": "EUR"},
                      now=NOW - timedelta(days=9))
    got = checkout.guard(conn, url="https://shop.test/cart", text="refund", now=NOW)
    assert [one["name"] for one in got["items"]] == ["Kettle X200"]
    assert got["items_from"] == "recent views"


def test_a_good_price_is_an_ok_finding_and_the_verdict_stays_go(conn):
    url = "https://shop.test/p/1"
    for day, price in enumerate([100, 110, 105, 100, 120, 100, 100]):
        pricewatch.record(conn, url, "Kettle", {"price": price, "currency": "EUR"},
                          now=NOW - timedelta(days=40 - day * 5))
    got = checkout.guard(conn, url="https://shop.test/cart", text="returns",
                         items=[{"name": "Kettle", "price": 99, "currency": "EUR", "url": url}], now=NOW)
    assert got["verdict"] == "go"
    assert any(one["kind"] == "price" and one["severity"] == "ok" for one in got["findings"])
