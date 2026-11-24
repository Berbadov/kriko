"""The other half of the buyer's ledger: what the reader decided *not* to buy.

A dodge is one press on a check, one line of reason and the price the listing
asked. It is kept in `app.sqlite` beside the purchases, because it is the
reader's own decision and neither a pack update nor an uninstall may erase it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import buyer, cloud
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


def test_a_dodge_keeps_one_line_and_the_price_it_avoided(conn):
    made = buyer.record_dodge(conn, "  Kettle   Pro \n", url="https://shop.test/k",
                              price="49,90", currency="eur",
                              reason="  hinge   cracks\nat the mount  ", when=NOW)
    assert made["name"] == "Kettle Pro"
    assert made["price"] == 49.9 and made["currency"] == "EUR"
    assert made["reason"] == "hinge cracks at the mount"
    assert made["decided_at"].startswith("2026-11-20T12:00:00")


def test_a_reason_is_a_capped_single_line(conn):
    made = buyer.record_dodge(conn, "Kettle", reason="x" * 500, when=NOW)
    assert len(made["reason"]) == buyer.MAX_DODGE_REASON


def test_the_same_listing_pressed_twice_is_one_dodge(conn):
    first = buyer.record_dodge(conn, "Kettle", url="https://shop.test/k", when=NOW)
    again = buyer.record_dodge(conn, "Kettle Pro", url="https://shop.test/k",
                               when=NOW + timedelta(hours=3))
    assert first["dodge_id"] == again["dodge_id"]
    assert len(buyer.dodged(conn)) == 1
    # A day later it is a new decision about the same page.
    later = buyer.record_dodge(conn, "Kettle", url="https://shop.test/k",
                               when=NOW + timedelta(days=2))
    assert later["dodge_id"] != first["dodge_id"]
    assert len(buyer.dodged(conn)) == 2


def test_a_check_with_no_page_is_deduped_by_its_name(conn):
    first = buyer.record_dodge(conn, "Kettle", when=NOW)
    again = buyer.record_dodge(conn, "Kettle", when=NOW + timedelta(hours=1))
    assert first["dodge_id"] == again["dodge_id"]
    assert len(buyer.dodged(conn)) == 1


def test_a_nameless_dodge_is_refused(conn):
    with pytest.raises(ValueError):
        buyer.record_dodge(conn, "   ")
    with pytest.raises(ValueError):
        buyer.record_dodge(conn, "Kettle", price="not a price")
    with pytest.raises(ValueError):
        buyer.record_dodge(conn, "Kettle", price=-1)


def test_the_ledger_is_newest_first(conn):
    buyer.record_dodge(conn, "Old", when=NOW)
    buyer.record_dodge(conn, "New", when=NOW + timedelta(days=1))
    assert [one["name"] for one in buyer.dodged(conn)] == ["New", "Old"]


def test_money_saved_keeps_currencies_apart_and_counts_the_unpriced(conn):
    buyer.record_dodge(conn, "A", price=100, currency="EUR", when=NOW)
    buyer.record_dodge(conn, "B", price=None, currency="EUR", when=NOW + timedelta(seconds=1))
    buyer.record_dodge(conn, "C", price="50", currency="USD", when=NOW + timedelta(seconds=2))
    buyer.record_dodge(conn, "D", price=0, currency="EUR", when=NOW + timedelta(seconds=3))
    saved = buyer.money_saved(conn)
    assert saved["count"] == 4 and saved["priced"] == 3
    assert saved["totals"] == [
        {"currency": "EUR", "amount": 100.0, "count": 3, "priced": 2},
        {"currency": "USD", "amount": 50.0, "count": 1, "priced": 1},
    ]


def test_an_empty_ledger_saves_nothing_and_says_so(conn):
    assert buyer.money_saved(conn) == {"totals": [], "count": 0, "priced": 0}


def test_the_dodged_ledger_is_bounded_to_the_newest(conn):
    for index in range(buyer.MAX_DODGED + 1):
        buyer.record_dodge(conn, f"Product {index}", url=f"https://shop.test/{index}",
                           when=NOW + timedelta(seconds=index))
    rows = buyer.dodged(conn, buyer.MAX_DODGED + 1)
    assert len(rows) == buyer.MAX_DODGED
    assert rows[0]["name"] == f"Product {buyer.MAX_DODGED}"
    assert "Product 0" not in {one["name"] for one in rows}


def test_forgetting_a_dodge_is_one_delete_and_a_second_says_no(conn):
    made = buyer.record_dodge(conn, "Kettle", when=NOW)
    assert buyer.forget_dodge(conn, made["dodge_id"]) is True
    assert buyer.forget_dodge(conn, made["dodge_id"]) is False
    assert buyer.dodged(conn) == []


@pytest.fixture
def paired(conn):
    state.put_settings(conn, {cloud.SERVER: "https://relay.example", cloud.KEY: "k" * 43})
    return conn


def test_forgetting_all_dodges_leaves_a_tombstone_for_a_paired_device(paired):
    kept = buyer.record_dodge(paired, "Kettle", price=40, when=NOW)
    assert buyer.forget(paired, "dodged") == 1
    assert buyer.dodged(paired) == []
    local = cloud._ledger_local(paired)
    assert kept["dodge_id"] in {one["key"] for one in local["dodged_deleted"]}


def test_the_holdings_name_the_dodges_and_their_label_is_readable(paired):
    buyer.record_dodge(paired, "Kettle", when=NOW)
    kept = buyer.holdings(paired)
    assert kept["dodged"] == 1 and kept["labels"]["dodged"] == "What you decided not to buy"


def test_forgetting_without_a_relay_keeps_no_dodge_tombstone(conn):
    made = buyer.record_dodge(conn, "Kettle", when=NOW)
    buyer.forget_dodge(conn, made["dodge_id"])
    assert not state.all_settings(conn).get(cloud.TOMBS)


def test_a_dodge_from_another_device_is_adopted_and_a_forgotten_one_stays_gone(paired):
    remote = {"purchases": [], "deleted": [], "dodged_deleted": [], "dodged": [{
        "dodge_id": "remote-1", "name": "Kettle", "url": "https://shop.test/k", "price": 30,
        "currency": "EUR", "reason": "hinge", "decided_at": NOW.isoformat()}]}
    cloud._ledger_merge(paired, cloud._ledger_local(paired), remote)
    assert [one["dodge_id"] for one in buyer.dodged(paired)] == ["remote-1"]
    assert buyer.forget(paired, "dodged") == 1
    merged = cloud._ledger_merge(paired, cloud._ledger_local(paired), remote)
    assert buyer.dodged(paired) == []
    assert "remote-1" in {one["key"] for one in merged["dodged_deleted"]}


def test_an_older_file_gains_the_table_from_the_schema(tmp_path):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    conn.execute("DROP TABLE dodged")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    again = state.connect(path)
    try:
        assert again.execute("SELECT COUNT(*) FROM dodged").fetchone()[0] == 0
    finally:
        again.close()


# ── the routes ───────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KRIKO_NO_PACK_AUTOUPDATE", "1")
    app = create_app(Settings(store_path=tmp_path / "k.sqlite", app_state_path=tmp_path / "app.sqlite",
                              analysis_log_path=tmp_path / "a.jsonl"))
    with TestClient(app) as client:
        yield client


def test_the_dodged_routes_list_add_and_remove(client):
    made = client.post("/api/buyer/dodged", json={
        "name": "Kettle", "url": "https://shop.test/k", "price": "49,90",
        "currency": "eur", "reason": "lid hinge cracks"}).json()
    assert made["name"] == "Kettle" and made["price"] == 49.9 and made["currency"] == "EUR"
    listing = client.get("/api/buyer/dodged").json()
    assert listing["count"] == 1 and listing["priced"] == 1
    assert listing["items"][0]["dodge_id"] == made["dodge_id"]
    assert listing["totals"] == [{"currency": "EUR", "amount": 49.9, "count": 1, "priced": 1}]
    assert client.delete(f"/api/buyer/dodged/{made['dodge_id']}").json() == {"deleted": made["dodge_id"]}
    assert client.delete(f"/api/buyer/dodged/{made['dodge_id']}").status_code == 404
    assert client.get("/api/buyer/dodged").json()["count"] == 0


def test_the_dodged_route_refuses_what_it_cannot_keep(client):
    assert client.post("/api/buyer/dodged", json={"name": "  "}).status_code == 422
    assert client.post("/api/buyer/dodged", json={"name": "Kettle", "reason": "x" * 201}).status_code == 422
    assert client.post("/api/buyer/dodged", json={"name": "Kettle", "price": -5}).status_code == 422
    assert client.post("/api/buyer/dodged", json={"name": "Kettle", "price": "abc"}).status_code == 422
    assert client.post("/api/buyer/dodged", json={"name": "Kettle", "url": "https://x.test/" + "u" * 3000}).status_code == 422


def test_the_privacy_screen_counts_and_forgets_dodges(client):
    client.post("/api/buyer/dodged", json={"name": "Kettle", "price": 40})
    kept = client.get("/api/buyer/privacy").json()
    assert kept["dodged"] == 1 and kept["labels"]["dodged"] == "What you decided not to buy"
    assert client.delete("/api/buyer/privacy/dodged").json()["rows"] == 1
    assert client.get("/api/buyer/privacy").json()["dodged"] == 0
    client.post("/api/buyer/dodged", json={"name": "Toaster", "price": 25})
    assert client.delete("/api/buyer/privacy/everything").json()["rows"] >= 1
    assert client.get("/api/buyer/dodged").json()["count"] == 0
