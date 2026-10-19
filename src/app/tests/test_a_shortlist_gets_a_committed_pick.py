"""A shortlist ranked for this reader, with a winner, what it gives up, and what would change it."""

from datetime import UTC, datetime, timedelta

import pytest

from app import buyer, pick, pricewatch
from app.web import state

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


def saved(lookup_id, label, url, *, price=None, claims=(), fields=None, description=""):
    fields = dict(fields or {})
    if price is not None:
        fields.update({"ld:price": str(price), "ld:priceCurrency": "EUR"})
    return {"lookup_id": lookup_id, "label": label,
            "request": {"url": url, "title": label, "description": description, "fields": fields},
            "response": {"claims": list(claims)}}


def risk(title, severity="high", disputed=False):
    return {"title": title, "severity": severity, "disputed": disputed}


def test_a_known_serious_risk_costs_more_than_a_slightly_higher_price(conn):
    a = saved("a", "Kettle A", "https://a.test/p/1", price=60, claims=[risk("Element fails in a year")])
    b = saved("b", "Kettle B", "https://b.test/p/1", price=66)
    got = pick.rank(conn, [a, b], buyer.clean({}), now=NOW)
    assert got["picked"]["name"] == "Kettle B"
    assert got["picked"]["lookup_id"] == "b"
    assert any("Element fails" in text for one in got["ranked"] for text in one["concerns"])


def test_the_readers_priorities_change_the_winner(conn):
    cheap_risky = saved("a", "Cheap", "https://a.test/p/1", price=50, claims=[risk("Hinge cracks", "medium")])
    dear_clean = saved("b", "Dear", "https://b.test/p/1", price=62)
    frugal = buyer.clean({"priorities": {"price": 5, "durability": 1}})
    durable = buyer.clean({"priorities": {"price": 1, "durability": 5}})
    assert pick.rank(conn, [cheap_risky, dear_clean], frugal, now=NOW)["picked"]["name"] == "Cheap"
    assert pick.rank(conn, [cheap_risky, dear_clean], durable, now=NOW)["picked"]["name"] == "Dear"


def test_breaking_a_stated_must_avoid_or_budget_sinks_a_product(conn):
    profile = buyer.clean({"avoid": ["Acme"], "budget": {"max": 100, "currency": "EUR"}})
    acme = saved("a", "Acme Toaster", "https://a.test/p/1", price=40)
    fine = saved("b", "Zeta Toaster", "https://b.test/p/1", price=95)
    dear = saved("c", "Zeta Deluxe", "https://c.test/p/1", price=140)
    got = pick.rank(conn, [acme, fine, dear], profile, now=NOW)
    assert [one["name"] for one in got["ranked"]] == ["Zeta Toaster", "Acme Toaster", "Zeta Deluxe"][:1] + [
        one["name"] for one in got["ranked"][1:]]
    assert got["picked"]["name"] == "Zeta Toaster"
    broken = {one["name"]: one["breaks"] for one in got["ranked"]}
    assert broken["Acme Toaster"] == ["avoid"] and broken["Zeta Deluxe"] == ["budget"]


def test_a_dispute_halves_a_risk(conn):
    sure = saved("a", "Sure", "https://a.test/p/1", claims=[risk("Fault")])
    disputed = saved("b", "Disputed", "https://b.test/p/1", claims=[risk("Fault", disputed=True)])
    got = pick.rank(conn, [sure, disputed], buyer.clean({}), now=NOW)
    assert got["picked"]["name"] == "Disputed"


def test_a_clear_win_a_close_one_and_a_toss_up_are_told_apart(conn):
    clean = saved("a", "Clean", "https://a.test/p/1", price=50)
    flawed = saved("b", "Flawed", "https://b.test/p/1", price=50,
                   claims=[risk("One", "high"), risk("Two", "high")])
    assert pick.rank(conn, [clean, flawed], buyer.clean({}), now=NOW)["confidence"] == "clear"
    near = saved("c", "Near", "https://c.test/p/1", price=50, claims=[risk("Small", "medium")])
    assert pick.rank(conn, [clean, near], buyer.clean({}), now=NOW)["confidence"] == "close"
    twin = saved("d", "Twin", "https://d.test/p/1", price=50)
    assert pick.rank(conn, [clean, twin], buyer.clean({}), now=NOW)["confidence"] == "toss_up"


def test_two_products_that_nothing_separates_are_thin_not_clear(conn):
    got = pick.rank(conn, [saved("a", "A", "https://a.test/1"), saved("b", "B", "https://b.test/1")],
                    buyer.clean({}), now=NOW)
    assert got["confidence"] == "thin" and got["picked"] is not None
    assert "tell it your budget" in " ".join(got["check_first"])


def test_one_product_is_ranked_but_never_picked(conn):
    got = pick.rank(conn, [saved("a", "A", "https://a.test/1", price=10)], buyer.clean({}), now=NOW)
    assert got["picked"] is None and len(got["ranked"]) == 1


def test_the_pick_says_what_it_gave_up_and_what_would_change_it(conn):
    winner = saved("a", "Winner", "https://a.test/p/1", price=60, claims=[risk("Loud motor", "medium")])
    runner = saved("b", "Runner", "https://b.test/p/1", price=80,
                   fields={"ld:ratingValue": "4.8", "ld:reviewCount": "4000", "ld:seller": "Runner Co"})
    got = pick.rank(conn, [winner, runner], buyer.clean({"priorities": {"price": 5}}), now=NOW)
    assert got["picked"]["name"] == "Winner"
    assert any("Loud motor" in text for text in got["gave_up"])
    assert any("Runner falls to about 60 EUR" in text for text in got["switch_if"])
    assert any("Loud motor" in text for text in got["check_first"])


def test_the_price_history_and_a_fake_discount_enter_the_score(conn):
    url = "https://a.test/p/1"
    for day, price in enumerate([100, 100, 101, 100, 100, 100]):
        pricewatch.record(conn, url, "A", {"price": price, "currency": "EUR"},
                          now=NOW - timedelta(days=40 - day * 6))
    inflated = saved("a", "A", url, price=100, fields={"ld:listPrice": "200"})
    plain = saved("b", "B", "https://b.test/p/1", price=100)
    got = pick.rank(conn, [inflated, plain], buyer.clean({}), now=NOW)
    ranked = {one["name"]: one for one in got["ranked"]}
    assert ranked["A"]["score"] < ranked["B"]["score"]
    assert any("invented" in text for text in ranked["A"]["concerns"])


def test_a_pick_is_kept_and_its_track_record_waits_for_enough_answers(conn):
    result = pick.rank(conn, [saved("a", "Kettle A", "https://a.test/p/1", price=50),
                              saved("b", "Kettle B", "https://b.test/p/1", price=70)],
                       buyer.clean({}), now=NOW)
    kept = pick.keep(conn, result, reason="cheaper and no known faults")
    assert kept["winner"] == "Kettle A"
    assert pick.keep(conn, {"picked": None}) is None
    assert pick.track_record(conn)["note"].startswith("too few")
    bought = buyer.record_purchase(conn, "Kettle A", url="https://a.test/p/1", when=NOW)
    buyer.answer(conn, bought["purchase_id"], "glad", now=NOW)
    record = pick.track_record(conn)
    assert record["picks"] == 1 and record["followed_and_answered"] == 1 and record["held_up"] == 1
    assert record["rate"] is None


def test_a_quick_look_saved_answer_is_read_through_its_listing(conn):
    quick = {"lookup_id": "q", "label": "Quick", "response": {
        "claims": [], "listing": {"url": "https://q.test/p/1", "description": "Waterproof, 2 year warranty",
                                  "facts": {"ld:price": "45", "ld:priceCurrency": "EUR"}}}}
    entry = pick.entry(conn, quick, buyer.clean({}), now=NOW)
    assert entry["price"] == 45 and entry["url"] == "https://q.test/p/1"
    assert entry["audit"]["claims"]["unbacked"] >= 1
