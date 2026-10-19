"""A price judged against what the same page said before, and a watch that speaks once."""

from datetime import UTC, datetime, timedelta

import pytest

from app import pricewatch
from app.web import state

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
URL = "https://shop.test/p/kettle-x200?utm_source=ad&id=42"


@pytest.fixture
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


def offer(price, was=None, currency="EUR"):
    return {"price": price, "was_price": was, "currency": currency, "seller": "", "in_stock": True}


def seen(conn, price, days, *, was=None, url=URL, name="Kettle X200"):
    return pricewatch.record(conn, url, name, offer(price, was), now=T0 + timedelta(days=days))


@pytest.mark.parametrize("text,expected", [
    ("1.299,90 TL", 1299.9), ("$1,299.90", 1299.9), ("1299.9", 1299.9), ("₺1.299", 1299.0),
    ("1,299", 1299.0), ("19,99", 19.99), ("12.5", 12.5), ("free", None), ("", None),
    (None, None), (True, None), (0, None), (-5, None),
])
def test_an_amount_is_read_the_way_the_page_wrote_it(text, expected):
    assert pricewatch.parse_amount(text) == expected


def test_the_same_page_under_a_tracking_link_is_one_page():
    a = pricewatch.product_key("https://www.Shop.test/p/Kettle-X200/?utm_source=ad&id=42&fbclid=z")
    b = pricewatch.product_key("https://shop.test/p/kettle-x200?id=42")
    assert a == b == "shop.test/p/kettle-x200?id=42"
    assert pricewatch.product_key("https://shop.test/p/x?id=43") != b


def test_a_scrape_with_no_price_is_remembered_as_nothing(conn):
    assert pricewatch.observe(conn, URL, "x", {"ld:name": "x"}) is None
    assert pricewatch.observe(conn, URL, "x", {"ld:lowPrice": "10", "ld:highPrice": "30"})["price"] == 10
    assert conn.execute("SELECT COUNT(*) FROM price_points").fetchone()[0] == 1


def test_a_range_is_never_reported_as_a_price():
    assert pricewatch.extract({"ld:highPrice": "30"}) == {}


def test_extract_reads_the_struck_through_price_and_stock():
    got = pricewatch.extract({"ld:price": "79,90", "ld:listPrice": "129,90", "ld:priceCurrency": "eur",
                              "ld:availability": "OutOfStock", "ld:seller": "Shop"})
    assert got == {"price": 79.9, "was_price": 129.9, "currency": "EUR", "seller": "Shop",
                   "in_stock": False}
    assert pricewatch.extract({"ld:price": "10", "ld:listPrice": "8"})["was_price"] is None


def test_the_same_price_within_hours_is_not_remembered_twice(conn):
    seen(conn, 50, 0)
    pricewatch.record(conn, URL, "k", offer(50), now=T0 + timedelta(hours=2))
    assert conn.execute("SELECT COUNT(*) FROM price_points").fetchone()[0] == 1
    pricewatch.record(conn, URL, "k", offer(45), now=T0 + timedelta(hours=3))
    pricewatch.record(conn, URL, "k", offer(50), now=T0 + timedelta(hours=9))
    assert conn.execute("SELECT COUNT(*) FROM price_points").fetchone()[0] == 3


def test_a_first_sighting_says_so_and_a_thin_history_does_not_judge():
    first = pricewatch.assess([], 50)
    assert first["verdict"] == "first" and "First time" in first["summary"]
    points = [{"price": 50, "seen_at": T0.isoformat()}, {"price": 50, "seen_at": (T0 + timedelta(days=1)).isoformat()}]
    thin = pricewatch.assess(points, 50)
    assert thin["verdict"] == "thin" and "too little" in thin["summary"]


def points_of(prices):
    return [{"price": p, "seen_at": (T0 + timedelta(days=i * 3)).isoformat()} for i, p in enumerate(prices)]


def test_the_lowest_usual_and_high_are_judged_against_the_median():
    history = points_of([100, 102, 99, 101, 100])
    assert pricewatch.assess(history, 90)["verdict"] == "lowest"
    assert pricewatch.assess(history, 100)["verdict"] == "usual"
    assert pricewatch.assess(history, 125)["verdict"] == "high"


def test_a_discount_the_history_cannot_support_is_called_inflated():
    history = points_of([100, 100, 101, 99, 100, 100])
    verdict = pricewatch.assess(history, 100, was_price=200)
    assert verdict["discount"] == "inflated" and verdict["claimed_pct"] == 50
    assert "never saw it above" in verdict["discount_summary"]


def test_a_sale_at_the_usual_price_is_called_the_usual_price():
    # One brief spike gave the "was" price a past; the rest of the time it costs this.
    history = points_of([100, 101, 124, 99, 100, 100])
    verdict = pricewatch.assess(history, 99, was_price=125)
    assert verdict["discount"] == "usual_price"


def test_a_real_discount_is_confirmed_by_a_higher_past():
    history = points_of([150, 148, 150, 149, 150, 150])
    verdict = pricewatch.assess(history, 120, was_price=150)
    assert verdict["discount"] == "real"


def test_a_claimed_discount_with_no_history_says_it_cannot_check_yet():
    verdict = pricewatch.assess([], 80, was_price=120)
    assert verdict["discount"] == "unknown" and "cannot check" in verdict["discount_summary"]


def test_judge_leaves_out_the_sighting_it_was_just_given(conn):
    for day, price in enumerate([100, 100, 100, 100]):
        seen(conn, price, day * 4)
    got = pricewatch.judge(conn, URL, offer(100), now=T0 + timedelta(days=13))
    assert got["count"] == 3 and got["verdict"] == "usual"


def test_currencies_are_never_mixed(conn):
    pricewatch.record(conn, URL, "k", offer(1000, currency="TRY"), now=T0)
    assert pricewatch.history(conn, pricewatch.product_key(URL), currency="EUR", now=T0) == []


def test_two_names_are_one_product_only_when_every_model_token_agrees():
    assert pricewatch.same_product("Sony WH-1000XM5 Black", "WH-1000XM5 headphones Sony")
    assert not pricewatch.same_product("Sony WH-1000XM5", "Sony WH-1000XM4")
    assert not pricewatch.same_product("Blue shirt", "Blue shirt cotton")
    assert not pricewatch.same_product("Phone 256GB", "Phone 128GB")


def test_elsewhere_lists_other_shops_cheapest_first_and_skips_the_same_shop(conn):
    name = "Sony WH-1000XM5"
    pricewatch.record(conn, "https://a.test/p/1", name, offer(300), now=T0)
    pricewatch.record(conn, "https://b.test/p/9", "WH-1000XM5 Sony", offer(270), now=T0)
    pricewatch.record(conn, "https://c.test/p/3", "Sony WH-1000XM4", offer(150), now=T0)
    pricewatch.record(conn, "https://a.test/p/2", name, offer(250), now=T0)
    found = pricewatch.elsewhere(conn, name, "https://a.test/p/1", "EUR", now=T0 + timedelta(days=1))
    assert [one["host"] for one in found] == ["b.test"]


def test_a_watch_alerts_at_the_target_once_and_again_only_lower(conn):
    seen(conn, 100, 0)
    held = pricewatch.watch(conn, URL, "Kettle", target=80, now=T0)
    assert held["started_price"] == 100
    seen(conn, 90, 1)
    assert pricewatch.alerts(conn) == []
    seen(conn, 79, 2)
    seen(conn, 79.5, 3)
    seen(conn, 78, 4)
    assert [one["price"] for one in pricewatch.alerts(conn)] == [78, 79]
    assert pricewatch.read_alerts(conn) == 2 and pricewatch.alerts(conn) == []


def test_a_watch_can_ask_for_a_fall_instead_of_a_price(conn):
    seen(conn, 100, 0)
    pricewatch.watch(conn, URL, "Kettle", drop_pct=20, now=T0)
    seen(conn, 85, 1)
    assert pricewatch.alerts(conn) == []
    seen(conn, 79, 2)
    assert pricewatch.alerts(conn)[0]["kind"] == "drop"


def test_watching_twice_changes_the_terms_and_a_bad_percentage_is_refused(conn):
    first = pricewatch.watch(conn, URL, "Kettle", target=50, now=T0)
    second = pricewatch.watch(conn, URL, "", target=40, now=T0)
    assert first["watch_id"] == second["watch_id"] and second["target"] == 40
    assert second["name"] == "Kettle"
    with pytest.raises(ValueError):
        pricewatch.watch(conn, URL, drop_pct=150)
    with pytest.raises(ValueError):
        pricewatch.watch(conn, "not a url")


def test_the_sweep_rereads_only_what_is_due_and_says_why_a_page_will_not_read(conn):
    page = ('<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer",'
            '"price":"59.00","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}</script>')
    pricewatch.watch(conn, URL, "Kettle", target=60, now=T0)
    pricewatch.watch(conn, "https://other.test/p/1", "Other", target=10, now=T0)
    pages = {pricewatch.strip_tracking(URL): page, "https://other.test/p/1": "<html>script-rendered</html>"}
    got = pricewatch.sweep(conn, lambda url: pages[url], now=T0 + timedelta(days=1))
    assert got == {"checked": 1, "failed": 1, "alerts": 1}
    bad = pricewatch.watch_for(conn, "https://other.test/p/1")
    assert "without a browser" in bad["last_error"]
    # Nothing is due an hour later.
    assert pricewatch.sweep(conn, lambda url: pytest.fail("fetched too soon"),
                            now=T0 + timedelta(days=1, hours=1)) == {"checked": 0, "failed": 0, "alerts": 0}


def test_a_fetch_that_raises_is_one_failure_not_the_end_of_the_sweep(conn):
    pricewatch.watch(conn, URL, "Kettle", target=60, now=T0)

    def boom(url):
        raise TimeoutError

    assert pricewatch.sweep(conn, boom, now=T0 + timedelta(days=1))["failed"] == 1
    assert "TimeoutError" in pricewatch.watches(conn)[0]["last_error"]


def test_meta_price_is_read_when_there_is_no_structured_offer():
    markup = ('<meta property="product:price:amount" content="12,50">'
              '<meta property="product:price:currency" content="GBP">')
    assert pricewatch.read_markup(markup) == {"price": 12.5, "was_price": None, "currency": "GBP",
                                              "seller": "", "in_stock": None}


def test_a_list_price_in_the_offers_specification_is_the_struck_price():
    markup = ('<script type="application/ld+json">{"offers":{"price":"70","priceCurrency":"EUR",'
              '"priceSpecification":[{"priceType":"https://schema.org/ListPrice","price":"100"}]}}</script>')
    assert pricewatch.read_markup(markup)["was_price"] == 100


def test_tracking_is_not_kept_in_the_address(conn):
    url = "https://shop.test/p/kettle?id=7&utm_source=ad&gclid=abc&color=red#reviews"
    assert pricewatch.strip_tracking(url) == "https://shop.test/p/kettle?id=7&color=red"
    pricewatch.record(conn, url, "Kettle", offer(40), now=T0)
    kept = conn.execute("SELECT url FROM price_points").fetchone()["url"]
    assert "utm_" not in kept and "gclid" not in kept and "#" not in kept
    held = pricewatch.watch(conn, url, "Kettle", target=30, now=T0)
    assert "utm_" not in held["url"] and "id=7" in held["url"]


def test_a_page_that_changes_its_price_on_every_load_cannot_fill_the_file(conn):
    for step in range(pricewatch.MAX_POINTS_PER_PAGE + 40):
        pricewatch.record(conn, URL, "Kettle", offer(40 + (step % 2)),
                          now=T0 + timedelta(hours=7 * step))
    count = conn.execute("SELECT COUNT(*) FROM price_points").fetchone()[0]
    assert count == pricewatch.MAX_POINTS_PER_PAGE
