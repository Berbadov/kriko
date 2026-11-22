"""A watch keeps what each check read, so a move can be told and drawn."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import buyer, pricewatch
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
URL = "https://shop.test/p/kettle-x200"


@pytest.fixture
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


def read(conn, price, *, hours=0, days=0, currency="EUR"):
    when = T0 + timedelta(days=days, hours=hours)
    pricewatch.record(conn, URL, "Kettle", {"price": price, "currency": currency}, now=when)


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM watch_prices").fetchone()[0]


def test_each_read_of_a_watched_page_is_kept_oldest_first(conn):
    held = pricewatch.watch(conn, URL, "Kettle", now=T0)
    read(conn, 100)
    read(conn, 95, days=1)
    read(conn, 98, days=2)
    got = pricewatch.price_history(conn, held["watch_id"])
    assert [one["price"] for one in got["items"]] == [100, 95, 98]
    assert got["items"][0]["seen_at"] < got["items"][2]["seen_at"]
    assert (got["low"], got["high"], got["first"], got["last"]) == (95, 100, 100, 98)


def test_a_page_nobody_watches_leaves_no_history(conn):
    read(conn, 100)
    assert count(conn) == 0


def test_the_same_price_again_the_same_day_is_not_a_new_row_but_a_new_day_is(conn):
    pricewatch.watch(conn, URL, "Kettle", now=T0)
    read(conn, 100)
    read(conn, 100, hours=7)
    assert count(conn) == 1
    read(conn, 90, hours=8)
    assert count(conn) == 2
    read(conn, 90, days=1)
    assert count(conn) == 3


def test_a_price_that_goes_back_to_an_earlier_one_is_kept(conn):
    pricewatch.watch(conn, URL, "Kettle", now=T0)
    read(conn, 100)
    read(conn, 90, hours=1)
    read(conn, 100, hours=2)
    assert count(conn) == 3


def test_a_watch_keeps_at_most_400_reads_and_drops_the_oldest(conn):
    held = pricewatch.watch(conn, URL, "Kettle", now=T0)
    for day in range(pricewatch.MAX_WATCH_READS + 5):
        read(conn, 100 + day, days=day)
    got = pricewatch.price_history(conn, held["watch_id"])
    assert len(got["items"]) == 400
    assert got["first"] == 105 and got["last"] == 100 + 404


def test_stopping_a_watch_deletes_its_history_and_forgetting_all_does_too(conn):
    held = pricewatch.watch(conn, URL, "Kettle", now=T0)
    other = pricewatch.watch(conn, "https://shop.test/p/other", "Other", now=T0)
    read(conn, 100)
    pricewatch.record(conn, "https://shop.test/p/other", "Other", {"price": 5, "currency": "EUR"}, now=T0)
    assert count(conn) == 2
    assert pricewatch.unwatch(conn, held["watch_id"], remember=False)
    assert [row[0] for row in conn.execute("SELECT watch_id FROM watch_prices")] == [other["watch_id"]]
    buyer.forget(conn, "watches")
    assert count(conn) == 0


def test_a_read_in_another_currency_than_the_watch_is_not_recorded_or_mixed(conn):
    held = pricewatch.watch(conn, URL, "Kettle", currency="EUR", now=T0)
    read(conn, 100)
    read(conn, 3000, hours=1, currency="TRY")
    assert [one["price"] for one in pricewatch.price_history(conn, held["watch_id"])["items"]] == [100]


def test_a_watch_with_no_reads_has_empty_figures_and_an_unknown_watch_has_none(conn):
    held = pricewatch.watch(conn, URL, "Kettle", now=T0)
    assert pricewatch.price_history(conn, held["watch_id"]) == {
        "items": [], "low": None, "high": None, "first": None, "last": None}
    assert pricewatch.price_history(conn, "nope") is None


def test_the_route_answers_in_the_shape_the_screen_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("KRIKO_NO_PACK_AUTOUPDATE", "1")
    app = create_app(Settings(store_path=tmp_path / "k.sqlite", app_state_path=tmp_path / "app.sqlite",
                              analysis_log_path=tmp_path / "a.jsonl"))
    with TestClient(app) as client:
        made = client.post("/api/prices/watches", json={"url": URL, "name": "Kettle"}).json()
        side = state.connect(tmp_path / "app.sqlite")
        read(side, 120)
        read(side, 110, days=1)
        side.close()
        got = client.get(f"/api/prices/watches/{made['watch_id']}/history").json()
        assert set(got) == {"items", "low", "high", "first", "last"}
        assert [one["price"] for one in got["items"]] == [120, 110]
        assert set(got["items"][0]) == {"price", "currency", "seen_at"}
        assert (got["low"], got["high"], got["first"], got["last"]) == (110, 120, 120, 110)
        assert client.get("/api/prices/watches/nope/history").status_code == 404
        client.delete(f"/api/prices/watches/{made['watch_id']}")
        assert client.get(f"/api/prices/watches/{made['watch_id']}/history").status_code == 404


def test_an_app_file_from_before_the_table_opens_and_gains_it(tmp_path):
    path = tmp_path / "app.sqlite"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE watches (watch_id TEXT PRIMARY KEY, product_key TEXT NOT NULL DEFAULT '',"
        " url TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', currency TEXT NOT NULL DEFAULT '',"
        " target REAL, drop_pct REAL, started_price REAL, created_at TEXT NOT NULL DEFAULT '',"
        " last_checked TEXT NOT NULL DEFAULT '', last_price REAL, last_error TEXT NOT NULL DEFAULT '',"
        " cloud INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT '');"
        "INSERT INTO watches (watch_id, product_key, url) VALUES ('w1', 'shop.test/p/x', 'https://shop.test/p/x');")
    old.commit()
    old.close()
    conn = state.connect(path)
    try:
        assert [one["watch_id"] for one in pricewatch.watches(conn)] == ["w1"]
        assert pricewatch.price_history(conn, "w1")["items"] == []
        index = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'watch_prices'").fetchall()
        assert any(row[0] == "watch_prices_seen" for row in index)
    finally:
        conn.close()
