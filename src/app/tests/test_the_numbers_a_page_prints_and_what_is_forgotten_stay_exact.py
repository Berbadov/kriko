"""Regressions from the 0.2.6 bug hunt: amounts, counts, addresses, and a forgotten row staying forgotten."""

from datetime import UTC, datetime, timedelta

import pytest

from app import audit, buyer, checkout, cloud, pricewatch
from app.web import state

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


@pytest.mark.parametrize("text", ["from 10 to 30", "10 - 30 TL", "199,90 TL 249,90 TL"])
def test_two_amounts_on_one_line_are_a_range_not_a_price(text):
    assert pricewatch.parse_amount(text) is None
    assert not pricewatch.extract({"shown:price": text})


@pytest.mark.parametrize("text,expected", [
    ("-50% 199,90 TL", 199.9), ("%18 KDV dahil 1.299,90 TL", 1299.9), ("1 299,90 €", 1299.9),
    ("1 299,90 TL", 1299.9), ("Price: $1,299.90", 1299.9),
])
def test_a_percentage_beside_a_price_is_not_part_of_it(text, expected):
    assert pricewatch.parse_amount(text) == expected


@pytest.mark.parametrize("typed,expected", [
    ("15.000", 15000.0), ("15,000", 15000.0), ("1.500,50", 1500.5), ("12.5", 12.5), ("12,5", 12.5), (800, 800.0),
])
def test_a_budget_is_read_the_way_a_shop_prints_it(typed, expected):
    assert buyer.clean({"budget": {"max": typed, "currency": "TRY"}})["budget"]["max"] == expected


def test_a_budget_in_thousands_does_not_make_a_normal_price_over_budget(conn):
    buyer.save(conn, {"budget": {"max": "15.000", "currency": "TRY"}})
    fit = buyer.fit(buyer.read(conn), name="Dyson V8", price=9000, currency="TRY")
    assert "budget" not in fit["breaks"]


@pytest.mark.parametrize("count", ["1,234", "1.234", "1234", "1 234 reviews"])
def test_a_review_count_is_a_whole_number(count):
    got = audit.reviews({"ld:ratingValue": "4.8", "ld:bestRating": "5", "ld:reviewCount": count})
    assert got["count"] == 1234


@pytest.mark.parametrize("url", [
    "https://shop.example.com/p?sku=A%26B", "https://shop.example.com/p?sku=A%23B",
    "https://shop.example.com/search?q=a%2Bb", "https://shop.example.com/search?q=lego+star+wars",
])
def test_a_watched_address_keeps_its_encoding(url):
    assert pricewatch.strip_tracking(url + "&utm_source=x") == url
    assert pricewatch.strip_tracking("https://shop.example.com/p?utm_source=x&sku=1&gclid=2") == \
        "https://shop.example.com/p?sku=1"


def test_a_price_with_no_currency_is_never_set_against_one_with_a_currency(conn):
    pricewatch.record(conn, "https://us-shop.example.com/p/1", "Sony WH-1000XM5 headphones",
                      {"price": 800.0, "currency": "USD"}, now=NOW - timedelta(days=1))
    got = checkout.guard(conn, url="https://tr-shop.example.com/sepet", now=NOW, text="iade 14 gun",
                         items=[{"name": "Sony WH-1000XM5 headphones", "price": "1.299,90", "currency": ""}])
    assert not [one for one in got["findings"] if one["kind"] == "cheaper"]


def test_a_recent_view_standing_in_for_the_cart_asks_and_does_not_stop(conn):
    pricewatch.record(conn, "https://shop.example.com/p/nova-256", "Phone Nova 256GB",
                      {"price": 900.0, "currency": "USD"}, now=NOW - timedelta(hours=3))
    conn.execute("INSERT INTO picks (pick_id, created_at, winner_name, winner_url, reason, pick_json)"
                 " VALUES ('p1', ?, 'Phone Nova 128GB', '', '', '{}')", (NOW.isoformat(),))
    conn.commit()
    got = checkout.guard(conn, url="https://shop.example.com/sepet", items=None, text="", now=NOW)
    variant = [one for one in got["findings"] if one["kind"] == "variant"]
    assert variant and variant[0]["severity"] == "check" and got["verdict"] != "stop"
    # With the cart actually read, the same mismatch is a stop.
    read = checkout.guard(conn, url="https://shop.example.com/sepet", now=NOW, text="",
                          items=[{"name": "Phone Nova 256GB", "price": 900, "currency": "USD"}])
    assert read["verdict"] == "stop"


@pytest.fixture
def paired(conn):
    state.put_settings(conn, {cloud.SERVER: "https://relay.example", cloud.KEY: "k" * 43})
    return conn


def test_forgetting_all_purchases_leaves_a_tombstone_for_each_so_a_paired_device_cannot_return_them(paired):
    row = buyer.record_purchase(paired, "Dyson V8", url="https://shop.test/p/1", price=500)
    local = cloud._ledger_local(paired)
    assert buyer.forget(paired, "purchases") == 1
    merged = cloud._ledger_merge(paired, cloud._ledger_local(paired),
                                 {"purchases": local["purchases"], "deleted": []})
    assert buyer.purchases(paired) == [] and row["purchase_id"] in {t["key"] for t in merged["deleted"]}


def test_forgetting_all_watches_leaves_a_tombstone_for_each(paired):
    pricewatch.watch(paired, "https://shop.test/p/kettle?utm_source=x", "Kettle", target=40, price=50, currency="USD")
    remote = {"watches": cloud._watches_local(paired)["watches"], "deleted": []}
    assert buyer.forget(paired, "watches") == 1
    cloud._watches_merge(paired, cloud._watches_local(paired), remote)
    assert pricewatch.watches(paired) == []


def test_forgetting_without_a_relay_keeps_no_tombstones(conn):
    buyer.record_purchase(conn, "Dyson V8", url="https://shop.test/p/1", price=500)
    buyer.forget(conn, "purchases")
    assert not state.all_settings(conn).get(cloud.TOMBS)


@pytest.mark.parametrize("typed", ["try", "TRY", "₺", "tl"])
def test_a_watch_keeps_its_currency_as_an_iso_code_so_it_can_alert(conn, typed):
    made = pricewatch.watch(conn, "https://shop.test/p/kettle", "Kettle", target=40, price=50, currency=typed)
    assert made["currency"] == "TRY"
